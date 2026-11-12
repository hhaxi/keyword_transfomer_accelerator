/* KWT framed stream over the Z100 PS Ethernet BSP (lwIP raw API). */
#include <stdint.h>
#include <string.h>
#include "kwt_infer.h"
#include "lwip/init.h"
#include "lwip/tcp.h"
#include "netif/xadapter.h"
#include "platform.h"
#include "platform_config.h"
#include "xil_printf.h"

#ifndef Z100_IP_LAST
#define Z100_IP_LAST 11
#endif

enum { PREFIX = 12, CRC_SIZE = 4, PORT = 5001, PAYLOAD = KWT_FEATURE_BYTES };
static uint8_t request[PREFIX + PAYLOAD + CRC_SIZE];
static uint8_t response[PREFIX + KWT_REPLY_BYTES + PAYLOAD + CRC_SIZE];
static unsigned received, expected, tx_length, tx_sent;
static struct tcp_pcb *client;
static struct netif interface;
struct netif *echo_netif = &interface; /* Used by the board timer code. */
extern volatile int TcpFastTmrFlag, TcpSlowTmrFlag;
void tcp_fasttmr(void);
void tcp_slowtmr(void);
/* Hooks consumed by newlib's constructor/destructor startup. */
void _init(void) {}
void _fini(void) {}

static uint32_t get_word(const uint8_t *p)
{
    return p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

static void put_word(uint8_t *p, uint32_t value)
{
    for (unsigned i = 0; i < 4; ++i)
        p[i] = value >> (8 * i);
}

static uint32_t crc32(const uint8_t *data, unsigned size)
{
    static const uint32_t nibble[16] = {
        0x00000000, 0x1db71064, 0x3b6e20c8, 0x26d930ac,
        0x76dc4190, 0x6b6b51f4, 0x4db26158, 0x5005713c,
        0xedb88320, 0xf00f9344, 0xd6d6a3e8, 0xcb61b38c,
        0x9b64c2b0, 0x86d3d2d4, 0xa00ae278, 0xbdbdf21c
    };
    uint32_t crc = 0xffffffff;
    for (unsigned i = 0; i < size; ++i) {
        crc ^= data[i];
        crc = (crc >> 4) ^ nibble[crc & 15];
        crc = (crc >> 4) ^ nibble[crc & 15];
    }
    return ~crc;
}

static void reset_connection(void *arg, err_t reason)
{
    (void)arg;
    (void)reason;
    client = NULL;
    received = expected = tx_length = tx_sent = 0;
}

static err_t receive(void *arg, struct tcp_pcb *pcb, struct pbuf *p, err_t reason)
{
    (void)arg;
    (void)reason;
    if (p == NULL) {
        tcp_err(pcb, NULL);
        reset_connection(NULL, ERR_OK);
        if (tcp_close(pcb) != ERR_OK) {
            tcp_abort(pcb);
            return ERR_ABRT;
        }
        return ERR_OK;
    }
    unsigned count = p->tot_len;
    if (count > sizeof(request) - received || tx_length != 0) {
        pbuf_free(p);
        tcp_abort(pcb);
        return ERR_ABRT;
    }
    pbuf_copy_partial(p, request + received, count, 0);
    pbuf_free(p);
    received += count;
    tcp_recved(pcb, count);
    if (received >= PREFIX) {
        uint32_t payload_length = get_word(request + 8);
        if (payload_length != PAYLOAD || received > sizeof(request) ||
            request[0] != 'K' || request[1] != 'W' || request[2] != 1 ||
            (request[3] != 3 && request[3] != 4)) {
            tcp_abort(pcb);
            return ERR_ABRT;
        }
        expected = PREFIX + payload_length + CRC_SIZE;
    }
    return ERR_OK;
}

static err_t accept(void *arg, struct tcp_pcb *pcb, err_t reason)
{
    (void)arg;
    (void)reason;
    if (client != NULL) {
        tcp_abort(pcb);
        return ERR_ABRT;
    }
    client = pcb;
    tcp_nagle_disable(pcb);
    tcp_recv(pcb, receive);
    tcp_err(pcb, reset_connection);
    return ERR_OK;
}

static void progress(unsigned completed, void *arg)
{
    (void)arg;
    uint8_t frame[PREFIX + 2 + CRC_SIZE];
    memcpy(frame, request, PREFIX);
    frame[3] |= 0x80;
    put_word(frame + 8, 2);
    frame[PREFIX] = 0x80;
    frame[PREFIX + 1] = completed;
    put_word(frame + PREFIX + 2, crc32(frame + 2, PREFIX));
    if (tcp_write(client, frame, sizeof(frame), TCP_WRITE_FLAG_COPY) == ERR_OK)
        tcp_output(client);
}

static void infer(void)
{
    unsigned crc_offset = expected - CRC_SIZE;
    if (crc32(request + 2, crc_offset - 2) != get_word(request + crc_offset)) {
        tcp_abort(client);
        return;
    }
    memcpy(response, request, PREFIX);
    memcpy(response + PREFIX, request + PREFIX, PAYLOAD);
    unsigned size = kwt_infer(response + PREFIX, request[3] == 4, progress, NULL);
    response[3] |= 0x80;
    put_word(response + 8, size);
    put_word(response + PREFIX + size, crc32(response + 2, PREFIX + size - 2));
    tx_length = PREFIX + size + CRC_SIZE;
    received = expected = tx_sent = 0;
}

static void send_result(void)
{
    while (tx_sent < tx_length) {
        unsigned count = tx_length - tx_sent;
        if (count > tcp_sndbuf(client))
            count = tcp_sndbuf(client);
        if (count == 0 || tcp_write(client, response + tx_sent, count, TCP_WRITE_FLAG_COPY) != ERR_OK)
            break;
        tx_sent += count;
    }
    tcp_output(client);
    if (tx_sent == tx_length)
        tx_length = 0;
}

int main(void)
{
    init_platform();
    *(volatile uint32_t *)0xf8f00208u = 1;
    lwip_init();
    ip_addr_t address, mask, gateway;
    IP4_ADDR(&address, 192, 168, 1, Z100_IP_LAST);
    IP4_ADDR(&mask, 255, 255, 255, 0);
    IP4_ADDR(&gateway, 0, 0, 0, 0);
    unsigned char mac[6] = { 0x02, 0x4b, 0x57, 0x54, 0x5a, Z100_IP_LAST };
    if (!xemac_add(&interface, &address, &mask, &gateway, mac, PLATFORM_EMAC_BASEADDR))
        return 1;
    netif_set_default(&interface);
    platform_enable_interrupts();
    netif_set_up(&interface);
    struct tcp_pcb *listener = tcp_new();
    if (listener == NULL || tcp_bind(listener, &address, PORT) != ERR_OK)
        return 2;
    listener = tcp_listen(listener);
    if (listener == NULL)
        return 3;
    tcp_accept(listener, accept);
    xil_printf("KWT TCP ready on 192.168.1.%d:%d\r\n", Z100_IP_LAST, PORT);
    for (;;) {
        if (TcpFastTmrFlag) {
            tcp_fasttmr();
            TcpFastTmrFlag = 0;
        }
        if (TcpSlowTmrFlag) {
            tcp_slowtmr();
            TcpSlowTmrFlag = 0;
        }
        xemacif_input(&interface);
        if (client != NULL && expected != 0 && received == expected && tx_length == 0)
            infer();
        if (client != NULL && tx_length != 0)
            send_result();
    }
}
