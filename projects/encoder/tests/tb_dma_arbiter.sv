`timescale 1ns/1ps
module tb_dma_arbiter;
    reg clk=0;always #5 clk=~clk;reg rst_n=0;
    integer cycles=0,fs=0,es=0,fr=0,er=0,delay_=0,refills=0,stalls=0;
    wire f_valid=fs<500,e_valid=es<500;
    wire [31:0] f_addr=32'h10000+32'(fs*4),e_addr=32'h20000+32'(es*4);
    wire [31:0] f_wdata=32'(fs)^32'h1234,e_wdata=32'(es)^32'h5678;
    wire f_read=fs%2==0,e_read=es%2==1;
    wire [3:0] f_mask=15,e_mask=3;
    wire f_ready,e_ready,f_rsp_valid,e_rsp_valid,f_err,e_err;
    wire [31:0] f_rdata,e_rdata,d_addr,d_wdata;wire [3:0] d_mask;
    wire f_rsp_ready=cycles%11<6,e_rsp_ready=cycles%13<7;
    wire d_valid,d_read,d_rsp_ready;
    reg pending=0;reg [31:0] reply=0;reg reply_error=0;
    wire d_rsp_valid=pending && delay_==0;
    wire d_ready=(!pending || (d_rsp_valid && d_rsp_ready)) && cycles%5!=0;
    wire [31:0] d_rdata=reply;wire d_err=reply_error;
    reg was_stalled=0;reg [68:0] held_offer;
    kwt_dma_arbiter dut(.*);
    always @(posedge clk) begin
        cycles<=cycles+1;
        if(cycles>30000) $fatal(1,"Arbiter deadlock");
        if(rst_n) begin
            if(was_stalled && (!d_valid || {d_addr,d_wdata,d_mask,d_read}!==held_offer)) $fatal(1,"Stalled grant changed");
            was_stalled<=d_valid && !d_ready;held_offer<={d_addr,d_wdata,d_mask,d_read};
            if(d_valid && !d_ready) stalls<=stalls+1;
            if(f_ready && f_valid) fs<=fs+1;
            if(e_ready && e_valid) es<=es+1;
            if(f_rsp_valid && f_rsp_ready) begin
                if(f_rdata!==((32'h10000+32'(fr*4))^32'hcafe1234) || f_err!==(fr%17==0)) $fatal(1,"FFN response owner/order");
                fr<=fr+1;
            end
            if(e_rsp_valid && e_rsp_ready) begin
                if(e_rdata!==((32'h20000+32'(er*4))^32'hcafe1234) || e_err!==(er%17==0)) $fatal(1,"Encoder response owner/order");
                er<=er+1;
            end
            if(f_rsp_valid && e_rsp_valid) $fatal(1,"Double response");
            if(pending && delay_>0) delay_<=delay_-1;
            if(d_rsp_valid && d_rsp_ready) pending<=0;
            if(d_valid && d_ready) begin
                if(d_rsp_valid && d_rsp_ready) refills<=refills+1;
                pending<=1;delay_<=cycles%4;reply<=d_addr^32'hcafe1234;
                if(d_addr[17]) begin
                    reply_error<=es%17==0;
                    if(!e_ready || !e_valid || d_addr!==e_addr || d_wdata!==e_wdata || d_mask!==e_mask || d_read!==e_read) $fatal(1,"Encoder grant");
                end else begin
                    reply_error<=fs%17==0;
                    if(!f_ready || !f_valid || d_addr!==f_addr || d_wdata!==f_wdata || d_mask!==f_mask || d_read!==f_read) $fatal(1,"FFN grant");
                end
            end
            if(fr==500 && er==500) begin
                if(refills<100 || stalls<10) $fatal(1,"Insufficient stress coverage");
                $display("ENC_ARBITER_PASS f=%0d e=%0d refills=%0d stalls=%0d",fr,er,refills,stalls);$finish;
            end
        end
    end
    initial begin repeat(4) @(negedge clk);rst_n=1;end
endmodule
