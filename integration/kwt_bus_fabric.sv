// KWT master arbitration in front of the E203 ICB address splitter.
module kwt_bus_fabric #(parameter integer DMA_BURST=1, HOST_BURST=0)(
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
    reg pending,pending_acc;
    reg [1:0] owner,next_owner,locked_owner;
    reg locked;
    // Weighted round robin: retain the DMA turn for a bounded number of
    // accepted commands, then visit CPU and host in the original order.
    // Count handshakes, never clocks; held grants and response stalls are intact.
    localparam BURST_W=DMA_BURST>1 ? $clog2(DMA_BURST) : 1;
    reg [BURST_W-1:0] dma_turn;
    // Optional bounded host priority. Count all host accepts since the last
    // CPU accept, including offers separated by blocking-driver gaps. Never
    // replenish on DMA service: doing so could starve CPU under H/D traffic.
    // Once exhausted, the original weighted round robin resumes. If CPU is
    // absent, ordinary arbitration still makes progress; no slot is reserved.
    localparam HOST_W=HOST_BURST>0 ? $clog2(HOST_BURST+1) : 1;
    reg [HOST_W-1:0] host_turn;
    reg [1:0] grant;
    reg host_boost;
    always @* begin
        grant=0;host_boost=0;
        if(locked) grant=locked_owner;
        else case(next_owner)
            0: if(c_valid) grant=0;else if(h_valid) grant=1;else grant=2;
            1: if(h_valid) grant=1;else if(d_valid) grant=2;else grant=0;
            default: if(d_valid) grant=2;else if(c_valid) grant=0;else grant=1;
        endcase
        if(!locked && HOST_BURST>0 && h_valid && host_turn<HOST_W'(HOST_BURST) && grant!=1) begin
            grant=1;host_boost=1;
        end
    end
    wire chosen_valid=grant==0?c_valid:(grant==1?h_valid:d_valid);
    wire [31:0] addr=grant==0?c_addr:(grant==1?h_addr:d_addr);
    wire [31:0] data=grant==0?c_wdata:(grant==1?h_wdata:d_wdata);
    wire read_=grant==0?c_read:(grant==1?h_read:d_read);
    wire [3:0] mask=grant==0?c_mask:(grant==1?h_mask:d_mask);
    // Preserve master-specific access permissions. Address zero selects a
    // registered error endpoint for denied and unmapped requests.
    wire acc_allowed=grant==0 && addr[31:20]==12'h400;
    wire ram_allowed=addr[31:19]==13'h1400 && (grant!=2 || addr>=32'ha0010000);
    wire [31:0] route_addr=(acc_allowed || ram_allowed) ? addr : 32'b0;
    wire ready,response_error;
    wire [31:0] response_data;
    // All local endpoints respond from registered state. Qualify completion
    // with the accepted route so the upstream zero-cycle bypass cannot feed
    // the next master request through the KWT DMA arbiter's retire path.
    wire response_valid=pending && (!pending_acc || a_rsp_valid);
    wire response_ready=owner==0?c_rsp_ready:(owner==1?h_rsp_ready:d_rsp_ready);
    wire retire=response_valid && response_ready;
    wire slot_free=!pending || retire;
    wire accept=chosen_valid && ready;
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

    wire [31:0] acc_addr,mem_addr;
    wire mem_valid,mem_ready,mem_read,mem_rsp_ready;
    wire err_valid,err_ready,err_rsp_ready;
    reg mem_pending,mem_response_read,err_pending;
    assign a_addr=acc_addr[19:0];
    assign ram_addr=mem_addr[18:2];
    assign ram_cs=mem_valid && mem_ready;
    assign ram_we=!mem_read;
    assign mem_ready=!mem_pending || mem_rsp_ready;
    assign err_ready=!err_pending || err_rsp_ready;
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            mem_pending<=0;
            mem_response_read<=0;
            err_pending<=0;
        end else begin
            if(mem_ready) mem_pending<=mem_valid;
            if(ram_cs) mem_response_read<=mem_read;
            if(err_ready) err_pending<=err_valid;
        end
    end

    sirv_icb1to8_bus #(
        // Keep room for retire/refill without feeding response-valid into the
        // splitter's command-valid path. Each endpoint has one response slot.
        .ICB_FIFO_DP(0),.SPLT_FIFO_OUTS_NUM(2),.SPLT_FIFO_CUT_READY(1),
        .O0_BASE_ADDR(32'ha0000000),.O0_BASE_REGION_LSB(19),
        .O1_BASE_ADDR(32'h40000000),.O1_BASE_REGION_LSB(20),
        .O2_BASE_ADDR(32'b0),.O2_BASE_REGION_LSB(0)
    ) e203_bus (
        .clk(clk),.rst_n(rst_n),
        .i_icb_cmd_valid(chosen_valid),.i_icb_cmd_ready(ready),
        .i_icb_cmd_addr(route_addr),.i_icb_cmd_read(read_),
        .i_icb_cmd_wdata(data),.i_icb_cmd_wmask(mask),
        .i_icb_cmd_lock(1'b0),.i_icb_cmd_excl(1'b0),.i_icb_cmd_size(2'b0),
        .i_icb_cmd_burst(2'b0),.i_icb_cmd_beat(2'b0),
        .i_icb_rsp_valid(),.i_icb_rsp_ready(pending && response_ready),
        .i_icb_rsp_err(response_error),.i_icb_rsp_rdata(response_data),.i_icb_rsp_excl_ok(),
        .o0_icb_enable(1'b1),.o0_icb_cmd_valid(mem_valid),.o0_icb_cmd_ready(mem_ready),
        .o0_icb_cmd_addr(mem_addr),.o0_icb_cmd_read(mem_read),
        .o0_icb_cmd_wdata(ram_wdata),.o0_icb_cmd_wmask(ram_mask),
        .o0_icb_rsp_valid(mem_pending),.o0_icb_rsp_ready(mem_rsp_ready),
        .o0_icb_rsp_rdata(mem_response_read ? ram_rdata : 32'b0),.o0_icb_rsp_err(1'b0),.o0_icb_rsp_excl_ok(1'b0),
        .o1_icb_enable(1'b1),.o1_icb_cmd_valid(a_valid),.o1_icb_cmd_ready(a_ready),
        .o1_icb_cmd_addr(acc_addr),.o1_icb_cmd_read(a_read),
        .o1_icb_cmd_wdata(a_wdata),.o1_icb_cmd_wmask(a_mask),
        .o1_icb_rsp_valid(a_rsp_valid),.o1_icb_rsp_ready(a_rsp_ready),
        .o1_icb_rsp_rdata(a_rdata),.o1_icb_rsp_err(a_err),.o1_icb_rsp_excl_ok(1'b0),
        .o2_icb_enable(1'b1),.o2_icb_cmd_valid(err_valid),.o2_icb_cmd_ready(err_ready),
        .o2_icb_rsp_valid(err_pending),.o2_icb_rsp_ready(err_rsp_ready),
        .o2_icb_rsp_rdata(32'b0),.o2_icb_rsp_err(1'b1),.o2_icb_rsp_excl_ok(1'b0),
        .o3_icb_enable(1'b0),.o3_icb_cmd_ready(1'b0),.o3_icb_rsp_valid(1'b0),.o3_icb_rsp_rdata(32'b0),.o3_icb_rsp_err(1'b0),.o3_icb_rsp_excl_ok(1'b0),
        .o4_icb_enable(1'b0),.o4_icb_cmd_ready(1'b0),.o4_icb_rsp_valid(1'b0),.o4_icb_rsp_rdata(32'b0),.o4_icb_rsp_err(1'b0),.o4_icb_rsp_excl_ok(1'b0),
        .o5_icb_enable(1'b0),.o5_icb_cmd_ready(1'b0),.o5_icb_rsp_valid(1'b0),.o5_icb_rsp_rdata(32'b0),.o5_icb_rsp_err(1'b0),.o5_icb_rsp_excl_ok(1'b0),
        .o6_icb_enable(1'b0),.o6_icb_cmd_ready(1'b0),.o6_icb_rsp_valid(1'b0),.o6_icb_rsp_rdata(32'b0),.o6_icb_rsp_err(1'b0),.o6_icb_rsp_excl_ok(1'b0),
        .o7_icb_enable(1'b0),.o7_icb_cmd_ready(1'b0),.o7_icb_rsp_valid(1'b0),.o7_icb_rsp_rdata(32'b0),.o7_icb_rsp_err(1'b0),.o7_icb_rsp_excl_ok(1'b0)
    );
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            pending<=0;pending_acc<=0;owner<=0;next_owner<=0;
            locked<=0;locked_owner<=0;
            dma_turn<=0;
            host_turn<=0;
        end else begin
            if(retire) pending<=0;
            if(slot_free && chosen_valid && !ready) begin locked<=1;locked_owner<=grant;end
            if(accept) begin
                pending<=1;pending_acc<=acc_allowed;owner<=grant;
                if(grant==0) host_turn<=0;
                else if(grant==1 && HOST_BURST>0 && host_turn<HOST_W'(HOST_BURST)) host_turn<=host_turn+1'b1;
                // An inserted host grant must not restart a partly consumed
                // DMA turn or move the saved cursor past a waiting CPU.
                if(host_boost) begin
                    next_owner<=next_owner;dma_turn<=dma_turn;
                end else if(grant==2 && DMA_BURST>1 && dma_turn<BURST_W'(DMA_BURST-1)) begin
                    next_owner<=2;dma_turn<=dma_turn+1'b1;
                end else begin
                    next_owner<=grant==2?2'd0:grant+1'b1;dma_turn<=0;
                end
                locked<=0;
            end
        end
    end
endmodule
