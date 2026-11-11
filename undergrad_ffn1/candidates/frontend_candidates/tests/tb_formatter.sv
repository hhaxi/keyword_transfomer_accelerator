`timescale 1ns/1ps
module tb_formatter;
 parameter PACKED40=1;
 reg clk=0; always #5 clk=~clk;
 reg rst_n=0,clear=0,in_valid=0,out_ready=0;
 reg [39:0] in_data=0;
 reg [14:0] in_index=0;
 wire in_ready,out_valid,empty,fault;
 wire [31:0] out_data;
 wire [15:0] out_index;
 kwt_output_formatter #(.PACKED40(PACKED40)) dut(.*);
 localparam N=1024;
 reg [39:0] values[0:N-1];
 reg [14:0] indices[0:N-1];
 reg [31:0] golden[0:2*N-1];
 reg [15:0] addresses[0:2*N-1];
 reg [159:0] bits160;
 reg [63:0] bits64;
 reg [31:0] random_state=32'h42c0ffee;
 integer i,j,first,word_count,sent,received,ticks,rounds,overlap;
 reg held=0,previous_stall=0;
 reg [31:0] previous_data;
 reg [15:0] previous_index;
 function automatic [31:0] next_random(input [31:0] value);
   next_random=value*32'd1664525+32'd1013904223;
 endfunction
 task automatic reset_queue;
   @(negedge clk); rst_n=0; in_valid=0; out_ready=0; clear=0;
   repeat(3) @(negedge clk);
   rst_n=1;
 endtask
 task automatic pulse_clear;
   @(negedge clk); clear=1; in_valid=0; out_ready=0;
   @(negedge clk); clear=0;
   if(!empty || fault || out_valid) $fatal(1,"Clear did not discard all state");
 endtask
 task automatic offer(input [39:0] data_,input [14:0] index_);
   @(negedge clk); in_valid=1; in_data=data_; in_index=index_;
   do @(posedge clk); while(!in_ready);
   @(negedge clk); in_valid=0;
 endtask
 task automatic stream(input integer scenario);
   begin
     sent=0;received=0;ticks=0;overlap=0;held=0;previous_stall=0;
     while(received<word_count) begin
       @(negedge clk);
       random_state=next_random(random_state);
       out_ready=(scenario==0) || (ticks>45 && ticks%211>60 && random_state[3:0]<11);
       if(!held) begin
         in_valid=sent<N && (scenario==0 || random_state[7:4]<13);
         if(in_valid) begin in_data=values[sent];in_index=indices[sent]; end
       end
       @(posedge clk);
       if(fault) $fatal(1,"Unexpected format fault");
       if(previous_stall && (!out_valid || out_data!==previous_data || out_index!==previous_index))
         $fatal(1,"Output changed under backpressure");
       previous_stall=out_valid && !out_ready;
       previous_data=out_data;previous_index=out_index;
       if(out_valid && out_ready) begin
         if(out_data!==golden[received] || out_index!==addresses[received])
           $fatal(1,"Mismatch word=%0d data=%h/%h index=%0d/%0d",received,out_data,golden[received],out_index,addresses[received]);
         received++;
       end
       if(in_valid && in_ready) begin
         sent++;
         if(out_valid && out_ready) overlap++;
       end
       held=in_valid && !in_ready;
       ticks++;
       if(ticks>50000) $fatal(1,"Formatter timeout");
     end
     @(negedge clk);in_valid=0;out_ready=0;
     if(sent!=N || !empty || overlap==0) $fatal(1,"Incomplete stream");
     $display("FORMAT_STREAM_PASS packed=%0d scenario=%0d words=%0d cycles=%0d overlaps=%0d",PACKED40,scenario,received,ticks,overlap);
   end
 endtask
 initial begin
   for(i=0;i<N;i++) begin
     random_state=next_random(random_state);
     values[i]={random_state[7:0],random_state};
     if(i%8==0) values[i]=40'h8000000000;
     if(i%8==1) values[i]=40'h7fffffffff;
     if(i%8==2) values[i]=40'hffffffffff;
     // Nonmonotonic groups mimic interleaved output rows; include highest index.
     first=(i/4==0) ? 25340 : ((i/4*37)%6336)*4;
     indices[i]=15'(first+i%4);
   end
   if(PACKED40) begin
     word_count=N/4*5;
     for(i=0;i<N/4;i++) begin
       bits160={values[i*4+3],values[i*4+2],values[i*4+1],values[i*4]};
       for(j=0;j<5;j++) begin golden[i*5+j]=bits160[j*32+:32];addresses[i*5+j]=(indices[i*4]/4)*5+j;end
     end
   end else begin
     word_count=N*2;
     for(i=0;i<N;i++) begin
       bits64={{24{values[i][39]}},values[i]};
       golden[i*2]=bits64[31:0];golden[i*2+1]=bits64[63:32];
       addresses[i*2]=indices[i]*2;addresses[i*2+1]=indices[i]*2+1;
     end
   end
   reset_queue();stream(0);stream(1);
   // Flush a partially assembled group, then restart from arbitrary valid index.
   offer(40'h12345,0);pulse_clear();stream(1);
   // Flush completed entries under downstream backpressure.
   for(i=0;i<(PACKED40 ? 8 : 2);i++) offer(40'(i),15'(i));
   pulse_clear();stream(0);
   if(PACKED40) begin
     offer(0,1);
     if(!fault || in_ready || out_valid) $fatal(1,"Unaligned group accepted");
     pulse_clear();offer(0,0);offer(1,2);
     if(!fault || in_ready || out_valid) $fatal(1,"Discontinuous group accepted");
     pulse_clear();stream(1);
   end
   // Asynchronous reset while entries are pending must also discard state.
   for(i=0;i<(PACKED40 ? 8 : 2);i++) offer(40'(i),15'(i));
   reset_queue();stream(0);
   $display("FORMATTER_PASS packed=%0d",PACKED40);$finish;
 end
 initial begin #10000000;$fatal(1,"Global formatter timeout");end
endmodule
