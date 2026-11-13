// Test-platform bulk loader. Read-only AXI bursts feed the SoC host port.
// The encoder and E203 have no connection to the AXI master.
module z100_contest_loader(
    input wire clk, rst_n, start,
    input wire [31:0] source,
    input wire [18:0] destination,
    input wire [15:0] words,
    output wire busy,
    output reg fault,
    output reg [31:0] araddr,
    output reg [7:0] arlen,
    output reg arvalid,
    input wire arready,
    input wire [31:0] rdata,
    input wire [1:0] rresp,
    input wire rvalid, rlast,
    output wire rready,
    output wire host_valid,
    input wire host_ready,
    output reg [18:0] host_addr,
    input wire host_response, host_error
);
    localparam IDLE=0, ADDRESS=1, DATA=2, DRAIN=3;
    reg [1:0] state;
    reg [15:0] remaining;
    reg [4:0] beats;
    reg pending;
    wire [10:0] page_words=11'd1024-{1'b0,araddr[11:2]};
    wire [4:0] page_limit=page_words<16 ? page_words[4:0] : 5'd16;
    wire [4:0] burst=remaining<{11'd0,page_limit} ? remaining[4:0] : page_limit;
    wire valid_request=words!=0 && source[1:0]==0 && destination[1:0]==0 &&
        {1'b0,destination}+{2'b0,words,2'b0}<=20'h80000;
    wire bad_beat=rresp!=0 || rlast!=(beats==1);
    assign busy=state!=IDLE;
    assign host_valid=state==DATA && rvalid && !fault && rresp==0;
    assign rready=state==DATA && (fault || rresp!=0 || host_ready);

    always @(posedge clk) begin
        if(!rst_n) begin
            state<=IDLE;fault<=0;arvalid<=0;araddr<=0;arlen<=0;
            host_addr<=0;remaining<=0;beats<=0;pending<=0;
        end else begin
            pending<=(pending && !host_response) || (host_valid && host_ready);
            if(host_response && host_error) fault<=1;
            case(state)
                IDLE: if(start) begin
                    fault<=!valid_request;
                    if(valid_request) begin
                        araddr<=source;host_addr<=destination;remaining<=words;state<=ADDRESS;
                    end
                end
                ADDRESS: if(!arvalid) begin
                    arlen<={3'd0,burst}-8'd1;beats<=burst;arvalid<=1;
                end else if(arready) begin
                    arvalid<=0;state<=DATA;
                end
                DATA: if(rvalid && rready) begin
                    beats<=beats-1'b1;
                    remaining<=remaining-1'b1;
                    host_addr<=host_addr+19'd4;
                    if(bad_beat) fault<=1;
                    if(rlast) begin
                        araddr<=araddr+{22'd0,arlen,2'b0}+32'd4;
                        state<=fault || bad_beat || remaining==1 || (host_response && host_error) ? DRAIN : ADDRESS;
                    end
                end
                DRAIN: if(!pending || host_response) state<=IDLE;
            endcase
        end
    end
endmodule
