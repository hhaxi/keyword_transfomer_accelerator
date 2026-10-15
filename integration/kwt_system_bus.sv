// Single outstanding System Bus transaction, host loader has priority.
// No arithmetic is performed here. CPU firmware handles all accelerator transfers.
module kwt_system_bus(
    input wire clk,rst_n,
    input wire c_valid,output wire c_ready,input wire [31:0] c_addr,c_wdata,
    input wire c_read,input wire [3:0] c_mask,
    output wire c_rsp_valid,input wire c_rsp_ready,output wire [31:0] c_rdata,output wire c_err,
    input wire h_valid,output wire h_ready,input wire [31:0] h_addr,h_wdata,
    input wire h_read,input wire [3:0] h_mask,
    output wire h_rsp_valid,input wire h_rsp_ready,output wire [31:0] h_rdata,output wire h_err
);
    reg pending,owner,acc_route,ram_route;
    wire [31:0] addr=h_valid?h_addr:c_addr;
    wire [31:0] wdata=h_valid?h_wdata:c_wdata;
    wire read_=h_valid?h_read:c_read;
    wire [3:0] mask=h_valid?h_mask:c_mask;
    wire sel_acc=addr[31:20]==12'h400 && !h_valid;
    wire sel_ram=addr[31:19]==13'h1400;
    wire a_ready,a_rsp_valid,a_err;
    wire [31:0] a_rdata,ramdata;
    wire ready=!pending && (!sel_acc || a_ready);
    wire accept=ready && (h_valid || c_valid);
    wire a_rsp_ready=pending && acc_route && (owner?h_rsp_ready:c_rsp_ready);
    wire valid=pending && (!acc_route || a_rsp_valid);
    wire error_=acc_route?a_err:!ram_route;
    assign h_ready=ready;
    assign c_ready=ready && !h_valid;
    assign c_rsp_valid=valid && !owner;
    assign h_rsp_valid=valid && owner;
    assign c_rdata=acc_route?a_rdata:(ram_route?ramdata:32'b0);
    assign h_rdata=c_rdata;
    assign c_err=error_;
    assign h_err=error_;
    always @(posedge clk or negedge rst_n)
        if(!rst_n) begin pending<=0;owner<=0;acc_route<=0;ram_route<=0;end
        else begin
            if(valid && (owner?h_rsp_ready:c_rsp_ready)) pending<=0;
            if(accept) begin pending<=1;owner<=h_valid;acc_route<=sel_acc;ram_route<=sel_ram;end
        end
    kwt_shared_sram shared(.clk(clk),.cs(accept && sel_ram),.we(!read_),.addr(addr[18:2]),
        .mask(mask),.din(wdata),.dout(ramdata));
    kwt_accel accelerator(.clk(clk),.rst_n(rst_n),.cmd_valid(!pending && !h_valid && c_valid && sel_acc),
        .cmd_ready(a_ready),.cmd_addr(addr[19:0]),.cmd_read(read_),.cmd_wdata(wdata),.cmd_wmask(mask),
        .rsp_valid(a_rsp_valid),.rsp_ready(a_rsp_ready),.rsp_rdata(a_rdata),.rsp_err(a_err));
endmodule
