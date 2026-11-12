#include <stdint.h>
#ifdef Z100_KWT
#include "kwt_infer.h"
#endif

#define UART(offset) (*(volatile uint32_t *)(0xe0000000u + (offset)))
#define PL(offset) (*(volatile uint32_t *)(0x43c00000u + (offset)))
#define TIMER_LO (*(volatile uint32_t *)0xf8f00200u)
#define TIMER_CTL (*(volatile uint32_t *)0xf8f00208u)

#ifndef Z100_BAUD
#define Z100_BAUD 115200
#endif
enum { HEADER_SIZE = 10, VERSION = 1 };
#ifdef Z100_KWT
enum { MAX_PAYLOAD = KWT_FEATURE_BYTES, BUFFER_SIZE = KWT_FEATURE_BYTES + KWT_REPLY_BYTES };
#else
enum { MAX_PAYLOAD = 32, BUFFER_SIZE = MAX_PAYLOAD };
#endif

static uint32_t get_word(const uint8_t *p)
{
    return p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

static void put_word(uint8_t *p, uint32_t v)
{
    for (unsigned i = 0; i < 4; ++i)
        p[i] = v >> (8 * i);
}

static uint32_t crc_bytes(uint32_t crc, const uint8_t *p, unsigned n)
{
    for (unsigned i = 0; i < n; ++i) {
        crc ^= p[i];
        for (unsigned bit = 0; bit < 8; ++bit)
            crc = (crc >> 1) ^ ((crc & 1) ? 0xedb88320u : 0);
    }
    return crc;
}

static int rx_byte(int timed)
{
    uint32_t start = TIMER_LO;
    while (UART(0x2c) & 0x02) {
        if (timed && TIMER_LO - start > 100000000u)
            return -1;
    }
    return UART(0x30) & 0xff;
}

static int read_bytes(uint8_t *data, unsigned count)
{
    for (unsigned i = 0; i < count; ++i) {
        int byte = rx_byte(1);
        if (byte < 0)
            return 0;
        data[i] = byte;
    }
    return 1;
}

static void send_bytes(const uint8_t *data, unsigned count)
{
    for (unsigned i = 0; i < count; ++i) {
        while (UART(0x2c) & 0x10) {}
        UART(0x30) = data[i];
    }
}

static void send_reply(uint8_t *header, const uint8_t *payload, unsigned size)
{
    const uint8_t magic[] = { 'K', 'W' };
    uint8_t checksum[4];
    header[1] |= 0x80;
    put_word(header + 6, size);
    uint32_t crc = crc_bytes(0xffffffffu, header, HEADER_SIZE);
    put_word(checksum, ~crc_bytes(crc, payload, size));
    send_bytes(magic, sizeof magic);
    send_bytes(header, HEADER_SIZE);
    send_bytes(payload, size);
    send_bytes(checksum, sizeof checksum);
}

#ifdef Z100_KWT
static void report_progress(unsigned completed, void *header)
{
    const uint8_t reply[2] = { 0x80, completed };
    send_reply(header, reply, sizeof reply);
}
#endif

int main(void)
{
    TIMER_CTL = 1;
    UART(0x00) = 0x28;
    UART(0x00) = 0x2b;
    UART(0x04) = 0x20;
    UART(0x18) = Z100_BAUD == 921600 ? 9 : 62;
    UART(0x34) = Z100_BAUD == 921600 ? 11 : 13;
    UART(0x00) = 0x14;

    int previous = 0;
    for (;;) {
        int next = rx_byte(0);
        if (previous != 'K' || next != 'W') {
            previous = next;
            continue;
        }
        previous = 0;
        uint8_t header[HEADER_SIZE], payload[BUFFER_SIZE], checksum[4];
        if (!read_bytes(header, sizeof header))
            continue;
        uint32_t size = get_word(header + 6);
        if (size > MAX_PAYLOAD || !read_bytes(payload, size) ||
            !read_bytes(checksum, sizeof checksum))
            continue;
        uint32_t crc = crc_bytes(0xffffffffu, header, sizeof header);
        if (header[0] != VERSION || get_word(checksum) != ~crc_bytes(crc, payload, size))
            continue;

        uint8_t response[13];
        response[0] = 0;
        if (header[1] == 1 && size == 0) {
            put_word(response + 1, PL(0));
            put_word(response + 5, PL(4));
            put_word(response + 9, PL(12));
            send_reply(header, response, sizeof response);
        } else if (header[1] == 2 && size == 4) {
            PL(8) = get_word(payload);
            __asm__ volatile ("dsb sy" ::: "memory");
            put_word(response + 1, PL(8));
            send_reply(header, response, 5);
#ifdef Z100_KWT
        } else if ((header[1] == 3 || header[1] == 4) && size == KWT_FEATURE_BYTES) {
            unsigned reply_size = kwt_infer(payload, header[1] == 4, report_progress, header);
            send_reply(header, payload, reply_size);
#endif
        } else {
            response[0] = 1;
            send_reply(header, response, 1);
        }
    }
}
