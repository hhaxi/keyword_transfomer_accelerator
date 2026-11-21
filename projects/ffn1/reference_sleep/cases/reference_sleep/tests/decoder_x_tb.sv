`timescale 1ns/1ps
module decoder_x_tb #(parameter TAIL_FIRST=0);
  reg clk=0,rst_n=0,clear=0,x_mode=1,in_valid=0,out_ready=0;
  always #5 clk=~clk;
  reg [31:0] in_word=0;
  wire in_ready,out_valid,metadata_valid,done,fault;
  wire [63:0] out_quad;
  wire [67:0] out_residual;
  wire [11:0] out_index;
  wire [13:0] expected_words;
  reg [3:0] x_query_tile=0;
  wire [8:0] x_query_words;
  kwt_weight_unpack #(.TAIL_FIRST(TAIL_FIRST)) dut(.*);
  reg [31:0] stream[0:3355];
  reg [67:0] expected[0:1599];
  reg [10:0] tags[0:1599];
  reg [8:0] counts[0:15];
  string prefix,test_name;
  integer word_count,offers=0,backpressure=0,t;
  reg [31:0] random_state=32'h58441;
  task restart(input bit async_reset);
    @(negedge clk); in_valid=0;out_ready=0;
    x_mode=1;
    if(async_reset)rst_n=0;else clear=1;
    repeat(2)@(negedge clk);
    rst_n=1;clear=1;
    @(negedge clk);
    if(out_valid || metadata_valid || done || fault)$fatal(1,"X clear retained state");
    clear=0;
  endtask
  task transfer(input integer stop_words,input integer stop_quads,input integer corrupt);
    integer sent,received,cycles,pending;
    reg stalled;
    reg [67:0] held;
    reg [11:0] held_index;
    reg [31:0] data;
    begin:session
      sent=0;received=0;cycles=0;pending=0;stalled=0;
      while(cycles<50000)begin
        @(negedge clk);
        random_state={random_state[30:0],random_state[31]^random_state[21]^random_state[1]^random_state[0]};
        if(!pending && sent<word_count && random_state[2:0]!=0)pending=1;
        in_valid=pending;data=sent<word_count ? stream[sent] : 32'hbad;
        // Every invalid-header case changes one independent contract field.
        if(corrupt==1 && sent==15)data=data^32'h00010000;
        if(corrupt==2 && sent==15)data=data^32'h00008000;
        if(corrupt==3 && sent==0)data=(data&32'hffffffe0)|32'd31;
        if(corrupt==4 && sent==0)data=(data&32'hffffffe0)|32'd16;
        if(corrupt==5 && sent==0)data=data|32'hc0000000;
        if(corrupt==5 && sent==1)data=data|32'h00000007;
        if(corrupt==6 && sent==1)data=(data&32'hffffe0ff)|32'h00001000;
        if(corrupt==7 && sent==15)data=data|32'h00007c00;
        in_word=data;
        // Session mode is sampled on clear, not combinationally from x_mode.
        if(cycles==32)x_mode=0;
        if(cycles==88)x_mode=1;
        out_ready=cycles>=96 && out_valid && random_state[5:3]<6 && cycles%511>=33;
        @(posedge clk);
        if(stalled && (!out_valid || held!==out_residual || held_index!==out_index))
          $fatal(1,"X offer changed under stall");
        stalled=out_valid && !out_ready;held=out_residual;held_index=out_index;
        if(stalled)offers=offers+1;
        if(in_valid && !in_ready)backpressure=backpressure+1;
        if(in_valid && in_ready)begin sent=sent+1;pending=0;end
        if(out_valid && out_ready)begin
          if(out_index!=={1'b0,tags[received]} || out_residual!==expected[received])
            $fatal(1,"X quad mismatch n=%0d tag=%0d expected=%017h got=%017h",received,out_index,expected[received],out_residual);
          received=received+1;
        end
        cycles=cycles+1;#1;
        if(corrupt && fault)begin
          if(out_valid || in_ready || metadata_valid)$fatal(1,"invalid X header remained active");
          repeat(3)begin @(posedge clk);#1;if(!fault)$fatal(1,"X header fault not sticky");end
          disable session;
        end
        if(!corrupt && fault)$fatal(1,"unexpected X decoder fault");
        if(!corrupt && metadata_valid!==(sent>=16))$fatal(1,"metadata mismatch sent=%0d",sent);
        if(metadata_valid && expected_words!==word_count)$fatal(1,"X expected size mismatch");
        if(sent==word_count && in_ready)$fatal(1,"X input overrun");
        if(done && received!=1600)$fatal(1,"X premature done");
        if((stop_words && sent>=stop_words)||(stop_quads && received>=stop_quads))disable session;
        if(received==1600)begin
          if(!done || out_valid || in_ready || sent!=word_count)$fatal(1,"X completion mismatch");
          @(negedge clk);in_valid=1;out_ready=1;
          repeat(4)begin @(posedge clk);#1;if(in_ready || out_valid || !done)$fatal(1,"X completion not quiescent");end
          disable session;
        end
      end
      $fatal(1,"X timeout sent=%0d received=%0d corrupt=%0d",sent,received,corrupt);
    end
  endtask
  initial begin
    if(!$value$plusargs("PREFIX=%s",prefix))$fatal(1,"PREFIX missing");
    if(!$value$plusargs("COUNT=%d",word_count))$fatal(1,"COUNT missing");
    if(!$value$plusargs("NAME=%s",test_name))test_name="x";
    $readmemh({prefix,"_input.hex"},stream,0,word_count-1);
    $readmemh({prefix,"_quads.hex"},expected);
    $readmemh({prefix,"_tags.hex"},tags);
    $readmemh({prefix,"_counts.hex"},counts);
    restart(1);
    transfer(0,0,0);
    for(t=0;t<16;t=t+1)begin
      x_query_tile=t;#1;
      if(x_query_words!==counts[t])$fatal(1,"tile query mismatch tile=%0d expected=%0d got=%0d",t,counts[t],x_query_words);
    end
    if(test_name=="extrema")begin
      restart(0);transfer(7,0,0);
      restart(1);transfer(20,0,0);
      restart(0);transfer(0,1599,0);
      for(t=1;t<=7;t=t+1)begin restart(0);transfer(0,0,t);end
      restart(0);transfer(0,0,0);
    end
    if(!offers || !backpressure)$fatal(1,"X missing stall coverage");
    $display("X_DECODER_PASS name=%0s tail=%0d words=%0d quads=1600 offers=%0d input_stalls=%0d",test_name,TAIL_FIRST,word_count,offers,backpressure);
    $finish;
  end
endmodule
