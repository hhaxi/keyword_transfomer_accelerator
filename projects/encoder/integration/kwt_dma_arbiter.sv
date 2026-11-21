// Two DMA engines share the existing fabric's master port. Keep a stalled
// offer stable and route each response using its accepted request owner.
module kwt_dma_arbiter(
    input wire clk,rst_n,
    input wire f_valid,output wire f_ready,input wire [31:0] f_addr,f_wdata,
    input wire f_read,input wire [3:0] f_mask,
    output wire f_rsp_valid,input wire f_rsp_ready,output wire [31:0] f_rdata,output wire f_err,
    input wire e_valid,output wire e_ready,input wire [31:0] e_addr,e_wdata,
    input wire e_read,input wire [3:0] e_mask,
    output wire e_rsp_valid,input wire e_rsp_ready,output wire [31:0] e_rdata,output wire e_err,
    output wire d_valid,input wire d_ready,output wire [31:0] d_addr,d_wdata,
    output wire d_read,output wire [3:0] d_mask,
    input wire d_rsp_valid,output wire d_rsp_ready,input wire [31:0] d_rdata,input wire d_err
);
    reg pending,owner,prefer_e,locked,locked_owner;
    wire grant=locked ? locked_owner : (prefer_e ? (e_valid || !f_valid) : (!f_valid && e_valid));
    wire retire=pending && d_rsp_valid && d_rsp_ready;
    wire free_=!pending || retire;
    assign d_valid=free_ && (grant ? e_valid : f_valid);
    assign d_addr=grant ? e_addr : f_addr;assign d_wdata=grant ? e_wdata : f_wdata;
    assign d_read=grant ? e_read : f_read;assign d_mask=grant ? e_mask : f_mask;
    assign e_ready=free_ && grant && d_ready;assign f_ready=free_ && !grant && d_ready;
    assign e_rsp_valid=pending && owner && d_rsp_valid;assign f_rsp_valid=pending && !owner && d_rsp_valid;
    assign d_rsp_ready=pending && (owner ? e_rsp_ready : f_rsp_ready);
    assign e_rdata=d_rdata;assign f_rdata=d_rdata;assign e_err=d_err;assign f_err=d_err;
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin pending<=0;owner<=0;prefer_e<=0;locked<=0;locked_owner<=0;end
        else begin
            if(retire) pending<=0;
            if(d_valid && !d_ready) begin locked<=1;locked_owner<=grant;end
            if(d_valid && d_ready) begin pending<=1;owner<=grant;prefer_e<=!grant;locked<=0;end
        end
    end
endmodule
