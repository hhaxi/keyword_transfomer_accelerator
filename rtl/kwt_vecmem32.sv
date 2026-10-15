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
            end else begin: single
                kwt_sram16 #(.AW(AW)) macro_(.clk(clk),.cs(cs && mask[l]),.we(we),.addr(addr),
                    .din(din[l*32+h*16+:16]),.dout(dout[l*32+h*16+:16]));
            end
        end
    end endgenerate
endmodule
