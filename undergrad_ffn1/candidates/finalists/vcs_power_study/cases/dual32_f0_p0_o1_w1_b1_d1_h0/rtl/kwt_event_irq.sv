// Optional always-clocked event latch. One outstanding MMIO response.
// Watchdog runs only while enable[2] is set; period is 2**WATCHDOG_BITS.
module kwt_event_irq #(parameter integer WATCHDOG_BITS=16) (
 input wire clk,rst_n,
 input wire cmd_valid, output wire cmd_ready,
 input wire [19:0] cmd_addr, input wire cmd_read,
 input wire [31:0] cmd_wdata, input wire [3:0] cmd_wmask,
 output reg rsp_valid, input wire rsp_ready,
 output reg [31:0] rsp_rdata, output reg rsp_err,
 input wire host_event,dma_event, output wire irq
);
 reg [2:0] enable,pending;
 reg [WATCHDOG_BITS-1:0] watchdog;
 wire accept=cmd_valid && cmd_ready;
 wire valid_addr=(cmd_addr==20'h80 || cmd_addr==20'h84 || cmd_addr==20'h88);
 wire write_enable=accept && !cmd_read && cmd_addr==20'h80 && cmd_wmask[0];
 wire write_clear=accept && !cmd_read && cmd_addr==20'h84 && cmd_wmask[0];
 wire [2:0] events={enable[2] && (&watchdog),dma_event,host_event};
 assign cmd_ready=!rsp_valid;
 assign irq=|(enable & pending);
 always @(posedge clk or negedge rst_n) begin
  if(!rst_n) begin
   enable<=0;pending<=0;watchdog<=0;rsp_valid<=0;rsp_rdata<=0;rsp_err<=0;
  end else begin
   if(enable[2]) watchdog<=watchdog+1'b1;else watchdog<=0;
   pending<=(pending & ~(write_clear ? cmd_wdata[2:0] : 3'b0)) | events;
   if(write_enable) enable<=cmd_wdata[2:0];
   if(rsp_valid && rsp_ready) rsp_valid<=0;
   if(accept) begin
    rsp_valid<=1;
    rsp_err<=!valid_addr || (!cmd_read && cmd_addr==20'h88);
    case(cmd_addr)
     20'h80:rsp_rdata<={29'b0,enable};
     20'h84:rsp_rdata<={29'b0,pending};
     20'h88:rsp_rdata<={29'b0,(pending & enable)};
     default:rsp_rdata<=0;
    endcase
   end
  end
 end
endmodule
