// Four independent 32-bit lanes, constructed only from allowed 16-bit SP macros.
// AW=11 is two 1024-word banks per lane; no 2048-word technology assumption.
module kwt_vecmem32 #(parameter AW=11)(
    input wire clk,cs,we,input wire [3:0] mask,input wire [AW-1:0] addr,
    input wire [127:0] din,output wire [127:0] dout
);
    genvar l,h,b;
    generate for(l=0;l<4;l=l+1) begin: lane
        for(h=0;h<2;h=h+1) begin: halfword
            if(AW==11) begin: split
                wire [15:0] q[0:1];reg bank;
                always @(posedge clk) if(cs && !we && mask[l]) bank<=addr[10];
                for(b=0;b<2;b=b+1) begin: block_
                    kwt_sram16 #(.AW(10)) macro_(.clk(clk),.cs(cs && mask[l] && addr[10]==(b==1)),
                        .we(we),.addr(addr[9:0]),.din(din[l*32+h*16+:16]),.dout(q[b]));
                end
                assign dout[l*32+h*16+:16]=q[bank];
            end else if(AW==8 || AW==9) begin: small_pages
                localparam PAGES=1<<(AW-7);
                wire [15:0] q[0:PAGES-1];
                reg [AW-8:0] page;
                always @(posedge clk) if(cs && !we && mask[l]) page<=addr[AW-1:7];
                for(b=0;b<PAGES;b=b+1) begin: block_
                    kwt_sram16 #(.AW(7)) macro_(.clk(clk),.cs(cs && mask[l] && addr[AW-1:7]==b),
                        .we(we),.addr(addr[6:0]),.din(din[l*32+h*16+:16]),.dout(q[b]));
                end
                assign dout[l*32+h*16+:16]=q[page];
            end else begin: single
                kwt_sram16 #(.AW(AW)) macro_(.clk(clk),.cs(cs && mask[l]),.we(we),.addr(addr),
                    .din(din[l*32+h*16+:16]),.dout(dout[l*32+h*16+:16]));
            end
        end
    end endgenerate
endmodule

// A row contains sixteen vectors of four words. Four banks expose adjacent
// vectors together for attention, while projections retain their narrow port.
module kwt_attention_mem #(parameter BANKS=4)(
    input wire clk, cs, we, wide,
    input wire [3:0] mask,
    input wire [10:0] addr,
    input wire [127:0] din,
    input wire [128*BANKS-1:0] wide_din,
    output wire [127:0] dout,
    output wire [128*BANKS-1:0] wide_dout
);
    localparam BITS=$clog2(BANKS);
    reg [BITS-1:0] read_bank;
    always @(posedge clk) if (cs && !we && !wide) read_bank <= addr[BITS-1:0];
    assign dout = wide_dout[128*read_bank+:128];
    genvar bank;
    generate for (bank=0; bank<BANKS; bank=bank+1) begin: banks
        kwt_vecmem32 #(.AW(11-BITS)) memory(
            .clk(clk), .cs(cs && (wide || addr[BITS-1:0]==bank)), .we(we),
            .mask(wide ? 4'hf : mask), .addr(addr[10:BITS]),
            .din(wide ? wide_din[128*bank+:128] : din),
            .dout(wide_dout[128*bank+:128])
        );
    end endgenerate
endmodule
