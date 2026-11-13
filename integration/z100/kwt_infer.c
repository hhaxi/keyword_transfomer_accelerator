#include "kwt_infer.h"
#ifdef Z100_ARM_CACHE
#include "xil_cache.h"
#endif

#ifdef Z100_USE_FATFS
#include "ff.h"
#endif

#ifndef Z100_FCLK_HZ
#define Z100_FCLK_HZ 25000000u
#endif

#ifdef Z100_CONTEST
#define DATA_WINDOW 0x43d00000u
#define CONTEST_CONTROL (*(volatile uint32_t *)(DATA_WINDOW + 0x80000u))
#define CONTEST_ID (*(volatile uint32_t *)(DATA_WINDOW + 0x80004u))
#define CONTEST_PC (*(volatile uint32_t *)(DATA_WINDOW + 0x80008u))
#else
#define DATA_WINDOW 0x10000000u
#endif
#define MODEL 0x11000000u
#define TIMER_LO (*(volatile uint32_t *)0xf8f00200u)
#define PL_CYCLES (*(volatile uint32_t *)0x43c0000cu)
#define ENC ((volatile uint32_t *)0x43c12000u)
#define FFN ((volatile uint32_t *)0x43c11000u)
#ifdef Z100_DIRECT_MODEL
#define MODEL_BASE (*(volatile uint32_t *)0x43c13000u)
#endif

enum { LAYERS = 12, LAYER_WORDS = 33410, CLASSES = 12, DIM = 64 };
enum { PARAMETER_WORDS = LAYERS * LAYER_WORDS + (DIM + 1) * CLASSES };
static const uint32_t *const model = (const uint32_t *)MODEL;
static int model_valid;

#ifdef Z100_PROFILE
enum { PROFILE_WORDS = 20 };
static volatile uint32_t *const profile = (volatile uint32_t *)0x11400000u;
#endif

static void put_word(uint8_t *p, uint32_t v)
{
    for (unsigned i = 0; i < 4; ++i)
        p[i] = v >> (8 * i);
}

static void barrier(void)
{
    __asm__ volatile ("dsb sy" ::: "memory");
}

#ifdef Z100_USE_FATFS
static void read_sd(void)
{
    static FATFS filesystem;
    FIL file;
    UINT count;
    if (f_mount(&filesystem, "0:/", 1) == FR_OK &&
        f_open(&file, "0:/kwt.bin", FA_READ) == FR_OK) {
        if (f_read(&file, (void *)MODEL, 16 + PARAMETER_WORDS * 4, &count) != FR_OK ||
            count != 16 + PARAMETER_WORDS * 4)
            *(volatile uint32_t *)MODEL = 0;
        f_close(&file);
    }
}
#endif

static int validate_model(void)
{
    if (model_valid)
        return 1;
#ifdef Z100_USE_FATFS
    if (model[0] != 0x5a54574bu)
        read_sd();
#endif
    if (model[0] != 0x5a54574bu || model[1] != 1 || model[2] != PARAMETER_WORDS * 4)
        return 0;
    const uint8_t *data = (const uint8_t *)(model + 4);
    uint32_t crc = 0xffffffffu;
    for (unsigned i = 0; i < PARAMETER_WORDS * 4; ++i) {
        crc ^= data[i];
        for (unsigned bit = 0; bit < 8; ++bit)
            crc = (crc >> 1) ^ ((crc & 1) ? 0xedb88320u : 0);
    }
    model_valid = ~crc == model[3];
    return model_valid;
}

#ifndef Z100_DIRECT_MODEL
static void store_words(unsigned offset, const uint32_t *source, unsigned count)
{
    volatile uint32_t *dst = (volatile uint32_t *)(DATA_WINDOW + offset);
    for (unsigned i = 0; i < count; ++i)
        dst[i] = source[i];
#if defined(Z100_ARM_CACHE) && !defined(Z100_CONTEST)
    Xil_DCacheFlushRange((uintptr_t)dst, count * sizeof(uint32_t));
#endif
}
#endif

#ifndef Z100_CONTEST
static unsigned wait_status(volatile uint32_t *registers)
{
    uint32_t started = TIMER_LO;
    uint32_t status;
    do {
        status = registers[1];
        if (TIMER_LO - started > 1000000000u)
            return 0xffffffffu;
    } while (status & 1);
    return status;
}

static unsigned run_engine(volatile uint32_t *registers)
{
    barrier();
    registers[0] = 1;
    barrier();
    return wait_status(registers);
}

#ifdef Z100_STREAM_HANDOFF
static void start_ffn(void)
{
    barrier();
    FFN[0] = 1;
    barrier();
}
#endif
#endif

static unsigned fail(uint8_t *packet, unsigned layer, unsigned stage, unsigned status)
{
    if (stage != 0) {
#ifdef Z100_CONTEST
        CONTEST_CONTROL = 1;
        barrier();
        CONTEST_CONTROL = 3;
        barrier();
#else
        ENC[0] = 2;
        FFN[0] = 2;
        barrier();
        wait_status(ENC);
        wait_status(FFN);
#endif
    }
    packet[0] = 2;
    packet[1] = layer;
    packet[2] = stage;
    put_word(packet + 3, status);
    return 7;
}

unsigned kwt_infer(uint8_t *packet, int verify, kwt_progress progress, void *context)
{
    if (!validate_model())
        return fail(packet, 0, 0, 1);
    uint32_t elapsed = 0;
#ifdef Z100_CONTEST
    if (CONTEST_ID != 0x4b575443u)
        return fail(packet, 0, 0, 2);
    volatile uint32_t *const mail = (volatile uint32_t *)(DATA_WINDOW + 0xf000u);
    // Reset control state between tasks. Every valid SRAM payload is overwritten
    // by the loader or its owning engine before use.
    CONTEST_CONTROL = 1;
    barrier();
    CONTEST_CONTROL = 3;
    barrier();
    mail[0] = 0;
    mail[1] = 0;
    CONTEST_CONTROL = 2;
    barrier();
    uint32_t started = PL_CYCLES;
    uint32_t progress_cycles = 0;
#endif
    volatile uint32_t *input = (volatile uint32_t *)(DATA_WINDOW + 0x10000);
    for (unsigned i = 0; i < KWT_FEATURE_BYTES; i += 4) {
        input[i / 4] = packet[i] | ((uint32_t)packet[i+1] << 8) |
            ((uint32_t)packet[i+2] << 16) | ((uint32_t)packet[i+3] << 24);
    }
#if defined(Z100_ARM_CACHE) && !defined(Z100_CONTEST)
    Xil_DCacheFlushRange((uintptr_t)input, KWT_FEATURE_BYTES);
#endif
#ifdef Z100_CONTEST
    for (unsigned layer = 0; layer < LAYERS; ++layer) {
        const uint32_t *p = model + 4 + layer * LAYER_WORDS;
        store_words(0x50000, p, 16704); p += 16704;
        store_words(0x20000, p, 8192); p += 8192;
        store_words(0x28000, p, 256); p += 256;
        store_words(0x40000, p, 8192); p += 8192;
        store_words(0x48000, p, 64); p += 64;
        mail[2] = p[0];
        mail[3] = p[1] | 24u | (layer != 0 ? 1u : 0u) | (layer != LAYERS - 1 ? 2u : 0u);
        mail[4] = layer;
        barrier();
        mail[0] = 11;
        barrier();
        uint32_t deadline = TIMER_LO;
        uint32_t status;
        do {
            status = mail[0];
            if (TIMER_LO - deadline > 1000000000u)
                return fail(packet, layer + 1, 3, 0xffffffffu);
        } while (status != 2 && status != 0xdeadu && status != 0xbadu);
        if (status == 0xbadu)
            return fail(packet, layer + 1, 3, CONTEST_PC);
        if (status != 2 || mail[1] != 0)
            return fail(packet, layer + 1, 3, mail[1]);
        const uint32_t layer_done = PL_CYCLES;
        if (layer + 1 == LAYERS)
            elapsed = layer_done - started - progress_cycles;
        progress(layer + 1, context);
        progress_cycles += PL_CYCLES - layer_done;
    }
#else
    ENC[0] = 4;
    ENC[0x20/4] = 0xa0010000u;
    ENC[0x24/4] = 0xa0050000u;
    ENC[0x28/4] = 0xa0018000u;
    ENC[0x2c/4] = 0xa0030000u;
    ENC[0x30/4] = 0xa0064000u;
    for (unsigned layer = 0; layer < LAYERS; ++layer) {
        uint32_t started = PL_CYCLES;
#ifdef Z100_PROFILE
        volatile uint32_t *trace = profile + layer * PROFILE_WORDS;
#endif
        const uint32_t *p = model + 4 + layer * LAYER_WORDS;
#ifdef Z100_DIRECT_MODEL
        MODEL_BASE = (uint32_t)(uintptr_t)p;
        p += LAYER_WORDS - 2;
#else
        store_words(0x50000, p, 16704); p += 16704;
        store_words(0x20000, p, 8192); p += 8192;
        store_words(0x28000, p, 256); p += 256;
        store_words(0x40000, p, 8192); p += 8192;
        store_words(0x48000, p, 64); p += 64;
#endif
        FFN[0x3c/4] = p[0];
        uint32_t config = p[1] | (layer != 0 ? 1u : 0u) | (layer != LAYERS - 1 ? 2u : 0u);
#ifdef Z100_STREAM_HANDOFF
        config |= 24u;
        start_ffn();
#endif
        ENC[0x34/4] = config;
        ENC[0x38/4] = 0;
#ifdef Z100_PROFILE
        trace[0] = PL_CYCLES - started;
#endif
        unsigned status = run_engine(ENC);
        if ((status & 0x1f) != 2)
            return fail(packet, layer + 1, 1, status);
#ifdef Z100_PROFILE
        trace[1] = ENC[0x40/4];
        for (unsigned phase = 0; phase < 10; ++phase)
            trace[4 + phase] = ENC[0x60/4 + phase];
        trace[14] = ENC[0x88/4];
        trace[15] = ENC[0x8c/4];
#endif
#ifdef Z100_STREAM_HANDOFF
        status = wait_status(FFN);
#else
        status = run_engine(FFN);
#endif
        if (status != 2)
            return fail(packet, layer + 1, 2, status);
#ifdef Z100_PROFILE
        trace[2] = FFN[0x40/4];
        trace[16] = FFN[0x44/4];
#endif
        ENC[0x38/4] = 1;
        status = run_engine(ENC);
        if ((status & 0x1f) != 2)
            return fail(packet, layer + 1, 3, status);
#ifdef Z100_PROFILE
        trace[3] = ENC[0x40/4];
        trace[17] = ENC[0x78/4];
        trace[18] = ENC[0x80/4];
        trace[19] = ENC[0x8c/4];
#endif
        elapsed += PL_CYCLES - started;
        progress(layer + 1, context);
    }
#if defined(Z100_PROFILE) && defined(Z100_ARM_CACHE)
    Xil_DCacheFlushRange((uintptr_t)profile, LAYERS * PROFILE_WORDS * sizeof(uint32_t));
#endif
#endif
#ifndef Z100_CONTEST
    uint32_t started = PL_CYCLES;
#endif
    const float *weights = (const float *)(model + 4 + LAYERS * LAYER_WORDS);
    const float *bias = weights + DIM * CLASSES;
    volatile const int32_t *output = (volatile const int32_t *)(DATA_WINDOW + 0x64000);
#if defined(Z100_ARM_CACHE) && !defined(Z100_CONTEST)
    Xil_DCacheInvalidateRange((uintptr_t)output, KWT_FEATURE_BYTES);
#endif
    unsigned best = 0;
    float best_score = 0;
    int32_t cls[DIM];
    for (unsigned i = 0; i < DIM; ++i)
        cls[i] = output[i];
    for (unsigned label = 0; label < CLASSES; ++label) {
        float score = 0;
        for (unsigned i = 0; i < DIM; ++i)
            score += ((float)cls[i] * (1.0f / 65536.0f)) * weights[i * CLASSES + label];
        score += bias[label];
        if (label == 0 || score > best_score) {
            best = label;
            best_score = score;
        }
        union { float f; uint32_t u; } result = { .f = score };
        put_word(packet + 10 + label * 4, result.u);
    }
#ifndef Z100_CONTEST
    elapsed += PL_CYCLES - started;
#endif
    packet[0] = 0;
    packet[1] = best;
    put_word(packet + 2, Z100_FCLK_HZ);
    put_word(packet + 6, elapsed);
    if (verify)
        for (unsigned i = 0; i < KWT_FEATURE_BYTES / 4; ++i)
            put_word(packet + KWT_REPLY_BYTES + 4 * i, output[i]);
    return KWT_REPLY_BYTES + (verify ? KWT_FEATURE_BYTES : 0);
}
