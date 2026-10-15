// Three-master round-robin ICB fabric. One response slot, retire/refill in
// the same cycle. The synchronous single-port SRAM remains single-ported.
module kwt_bus_fabric(
    input wire clk,rst_n,
    input wire c_valid,output wire c_ready,input wire [31:0] c_addr,c_wdata,
    input wire c_read,input wire [3:0] c_mask,
    output wire c_rsp_valid,input wire c_rsp_ready,output wire [31:0] c_rdata,output wire c_err,
    input wire h_valid,output wire h_ready,input wire [31:0] h_addr,h_wdata,
    input wire h_read,input wire [3:0] h_mask,
    output wire h_rsp_valid,input wire h_rsp_ready,output wire [31:0] h_rdata,output wire h_err,
    input wire d_valid,output wire d_ready,input wire [31:0] d_addr,d_wdata,
    input wire d_read,input wire [3:0] d_mask,
    output wire d_rsp_valid,input wire d_rsp_ready,output wire [31:0] d_rdata,output wire d_err,
    output wire a_valid,input wire a_ready,output wire [19:0] a_addr,
    output wire a_read,output wire [31:0] a_wdata,output wire [3:0] a_mask,
    input wire a_rsp_valid,output wire a_rsp_ready,input wire [31:0] a_rdata,input wire a_err,
    output wire ram_cs,ram_we,output wire [16:0] ram_addr,output wire [3:0] ram_mask,
    output wire [31:0] ram_wdata,input wire [31:0] ram_rdata
);
    reg pending,acc_route,ram_route,response_read;
    reg [1:0] owner,next_owner,locked_owner;
    reg locked;
    reg [1:0] grant;
    always @* begin
        grant=0;
        if(locked) grant=locked_owner;
        else case(next_owner)
            0: if(c_valid) grant=0;else if(h_valid) grant=1;else grant=2;
            1: if(h_valid) grant=1;else if(d_valid) grant=2;else grant=0;
            default: if(d_valid) grant=2;else if(c_valid) grant=0;else grant=1;
        endcase
    end
    wire chosen_valid=grant==0?c_valid:(grant==1?h_valid:d_valid);
    wire [31:0] addr=grant==0?c_addr:(grant==1?h_addr:d_addr);
    wire [31:0] data=grant==0?c_wdata:(grant==1?h_wdata:d_wdata);
    wire read_=grant==0?c_read:(grant==1?h_read:d_read);
    wire [3:0] mask=grant==0?c_mask:(grant==1?h_mask:d_mask);
    wire sel_acc=grant==0 && addr[31:20]==12'h400;
    wire sel_ram=addr[31:19]==13'h1400 && (grant!=2 || addr>=32'ha0010000);
    wire response_valid=pending && (!acc_route || a_rsp_valid);
    wire response_ready=owner==0?c_rsp_ready:(owner==1?h_rsp_ready:d_rsp_ready);
    wire retire=response_valid && response_ready;
    wire slot_free=!pending || retire;
    wire ready=slot_free && (!sel_acc || a_ready);
    wire accept=chosen_valid && ready;
    wire [31:0] response_data=acc_route?a_rdata:((ram_route && response_read)?ram_rdata:32'b0);
    wire response_error=acc_route?a_err:!ram_route;
    assign c_ready=ready && grant==0;
    assign h_ready=ready && grant==1;
    assign d_ready=ready && grant==2;
    assign c_rsp_valid=response_valid && owner==0;
    assign h_rsp_valid=response_valid && owner==1;
    assign d_rsp_valid=response_valid && owner==2;
    assign c_rdata=response_data;
    assign h_rdata=response_data;
    assign d_rdata=response_data;
    assign c_err=response_error;
    assign h_err=response_error;
    assign d_err=response_error;
    assign a_valid=slot_free && chosen_valid && sel_acc;
    assign a_addr=addr[19:0];assign a_wdata=data;assign a_read=read_;assign a_mask=mask;
    assign a_rsp_ready=pending && acc_route && response_ready;
    assign ram_cs=accept && sel_ram;assign ram_we=!read_;
    assign ram_addr=addr[18:2];assign ram_mask=mask;assign ram_wdata=data;
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            pending<=0;owner<=0;next_owner<=0;acc_route<=0;ram_route<=0;response_read<=0;
            locked<=0;locked_owner<=0;
        end else begin
            if(retire) pending<=0;
            if(slot_free && chosen_valid && !ready) begin locked<=1;locked_owner<=grant;end
            if(accept) begin
                pending<=1;owner<=grant;acc_route<=sel_acc;ram_route<=sel_ram;response_read<=read_;
                next_owner<=grant==2?2'd0:grant+1'b1;locked<=0;
            end
        end
    end
endmodule
