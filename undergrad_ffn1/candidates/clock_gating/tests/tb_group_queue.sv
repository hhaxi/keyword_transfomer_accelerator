`timescale 1ns/1ps
module tb_group_queue;
 parameter DEPTH=1;
 reg clk=0;always #5 clk=~clk;
 reg rst_n=0,clear=0,in_valid=0,out_ready=0;
 reg [1279:0] in_values=0;
 wire in_ready,out_valid;
 wire [39:0] out_value;
 wire [14:0] out_index;
 kwt_group_queue #(.DEPTH(DEPTH)) dut(.*);
 integer sent,received,cycle_count,group_id,lane_id,base_row,col_id,expected_index;
 integer i,round_id,simultaneous;
 reg held,stalled;
 reg [39:0] held_value;
 reg [14:0] held_index;
 reg [31:0] rng=32'hc01dcafe;
 function automatic [31:0] next_random(input [31:0] x);next_random=x*1664525+1013904223;endfunction
 function automatic [39:0] value_at(input integer group_no,input integer lane_no);
   reg [31:0] v;
   begin
     v=32'(group_no)*32'hc93dba51+32'(lane_no)*32'h37ef0b93;
     value_at={v[7:0]^8'h80,v};
     if(lane_no==0)value_at=40'h8000000000;
     if(lane_no==1)value_at=40'h7fffffffff;
   end
 endfunction
 task automatic flush(input bit reset_);
   @(negedge clk);in_valid=0;out_ready=0;
   if(reset_)rst_n=0;else clear=1;
   @(negedge clk);rst_n=1;clear=0;
   if(out_valid) $fatal(1,"Queue visible after reset/clear");
 endtask
 task automatic stream(input integer pattern,input integer limit);
   begin
     sent=0;received=0;cycle_count=0;held=0;stalled=0;simultaneous=0;
     while(received<limit)begin
       @(negedge clk);rng=next_random(rng);
       out_ready=pattern==0 || (cycle_count%503>127 && rng[3:0]<11);
       if(!held)begin
         in_valid=sent<800 && (pattern==0 || rng[7:4]<11);
         for(i=0;i<32;i++)in_values[i*40+:40]=value_at(sent,i);
       end
       @(posedge clk);
       if(stalled && (!out_valid || out_value!==held_value || out_index!==held_index))
         $fatal(1,"Changed output while stalled");
       stalled=out_valid && !out_ready;held_value=out_value;held_index=out_index;
       if(out_valid && out_ready)begin
         if(received<24576)begin group_id=received/32;lane_id=received%32;end
         else begin group_id=768+(received-24576)/24;lane_id=(received-24576)%24;end
         base_row=(group_id/32)*4;col_id=(group_id%32)*8;
         expected_index=(base_row+lane_id/8)*256+col_id+lane_id%8;
         if(out_value!==value_at(group_id,lane_id) || out_index!==15'(expected_index))
           $fatal(1,"Queue mismatch result=%0d index=%0d expected=%0d",received,out_index,expected_index);
         received++;
       end
       if(in_valid && in_ready)begin
         sent++;
         if(out_valid && out_ready)simultaneous++;
       end
       held=in_valid && !in_ready;
       cycle_count++;
       if(cycle_count>200000)$fatal(1,"Queue timeout");
     end
     @(negedge clk);in_valid=0;out_ready=0;
     if(limit==25344 && (sent!=800 || out_valid || simultaneous==0))$fatal(1,"Incomplete drain");
     $display("QUEUE_STREAM_PASS depth=%0d pattern=%0d outputs=%0d cycles=%0d simultaneous=%0d",DEPTH,pattern,received,cycle_count,simultaneous);
   end
 endtask
 initial begin
   flush(1);stream(0,25344);
   flush(0);stream(1,25344);
   flush(0);stream(1,113);flush(0);stream(1,25344);
   flush(0);stream(1,91);flush(1);stream(0,25344);
   $display("GROUP_QUEUE_PASS depth=%0d",DEPTH);$finish;
 end
 initial begin #15000000;$fatal(1,"Global timeout");end
endmodule
