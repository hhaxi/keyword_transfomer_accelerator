`timescale 1ns/1ps
// Companion unit test: FFN values are independent input vectors here.
// End-to-end SoC tests separately run the real FFN hardware between commands.
module tb_encoder;
    reg clk=0;always #3.333 clk=~clk;
    reg rst_n=0,cmd_valid=0,cmd_read=0,rsp_ready=1;
    reg [19:0] cmd_addr=0;reg [31:0] cmd_wdata=0;reg [3:0] cmd_wmask=15;
    wire cmd_ready,rsp_valid,rsp_err;wire [31:0] rsp_rdata;
    wire m_valid,m_read,m_rsp_ready;wire [31:0] m_addr,m_wdata;wire [3:0] m_mask;
    integer dma_mode=2,queued=0,due[0:1],max_queued=0,refills=0,read_streak=0,write_streak=0,max_read_streak=0,max_write_streak=0;
    reg head=0,tail=0;reg [31:0] response_data[0:1];
    wire m_ready=queued<(dma_mode==0 ? 1 : 2) && (dma_mode==1 || cycles%7!=0);
    wire m_rsp_valid=queued!=0 && cycles>=due[head];
    wire [31:0] m_rdata=response_data[head];wire m_err=0;
    reg held=0;reg [31:0] held_addr,held_data;reg held_read;
    reg [31:0] mem[0:131071],params[0:16703],initial_x[0:6335],expected[0:6335],packed_x[0:3167],cfg[0:1];
    reg [63:0] ffn_expected[0:6335];
    reg [31:0] rd;
    integer cycles=0,j,li,layers=12,polls,constant_edge=0,transport=0,stream_index=0;
    reg stream_feed=0,link_abort_in=0;
    wire result_valid=stream_feed && stream_index<6336;
    wire result_ready,link_abort_out;
    wire [39:0] result_data=ffn_expected[stream_index<6336 ? stream_index : 0][39:0];
    reg [159:0] packed_group;
    always @(posedge clk) if(result_valid && result_ready) stream_index<=stream_index+1;
    reg [31:0] counted_cycles;longint phase_sum;
    string folder;
`ifdef ENCODER_TRACE
    reg [31:0] tq[0:6335],tk[0:6335],tv[0:6335],tc[0:6335],ta[0:6335],tr1[0:6335],tz[0:6335],tr2[0:6335];
    reg [31:0] ts[0:9800],tp[0:9800];
    integer idx;
    always @(posedge clk) if(rst_n && !dut.stopping) begin
        if(dut.state==dut.SSAVE && dut.si!==ts[integer'(dut.row)*99+integer'(dut.keyrow)]) $fatal(1,"QK/scale trace mismatch");
        if(dut.state==dut.NCALC && dut.si!==tp[integer'(dut.row)*99+integer'(dut.k)]) $fatal(1,"Softmax trace mismatch");
        for(integer t=0;t<4;t++) begin
            idx=integer'(dut.row)*64+integer'(dut.group_)*4+t;
            if(dut.state==dut.PSAVE) begin
                if(dut.projection==0 && dut.qi[t*32+:32]!==tq[idx]) $fatal(1,"Q trace mismatch");
                if(dut.projection==1 && dut.ki[t*32+:32]!==tk[idx]) $fatal(1,"K trace mismatch");
                if(dut.projection==2 && dut.vi[t*32+:32]!==tv[idx]) $fatal(1,"V trace mismatch");
            end
            if(dut.state==dut.VSAVE && dut.qi[t*32+:32]!==tc[idx]) $fatal(1,"PV trace mismatch");
            if(dut.state==dut.RSAVE && (dut.clip32(dut.projected[t])!==ta[idx] || dut.xi[t*32+:32]!==tr1[idx])) $fatal(1,"Output projection/residual1 trace mismatch");
            if(dut.state==dut.AFFINE && !dut.norm_second && dut.xi[t*32+:32]!==tz[idx]) $fatal(1,"LN1 trace mismatch");
            if(dut.state==dut.TSTORE && dut.xi[t*32+:32]!==tr2[integer'(dut.tail_index>>3)*4+t]) $fatal(1,"Residual2 trace mismatch");
        end
    end
`endif
    kwt_encoder #(.STREAM_ENABLE(1)) dut(.*);
    always @(posedge clk) begin
        cycles<=cycles+1;
        if(cycles>30000000) $fatal(1,"Encoder timeout state=%0d",dut.state);
        if(!rst_n) begin queued<=0;head<=0;tail<=0;held<=0;end
        else begin
            if(held && (!m_valid || m_addr!==held_addr || m_wdata!==held_data || m_read!==held_read)) $fatal(1,"DMA offer changed under backpressure");
            held<=m_valid && !m_ready;held_addr<=m_addr;held_data<=m_wdata;held_read<=m_read;
            case({m_valid && m_ready,m_rsp_valid && m_rsp_ready})
                2'b10:queued<=queued+1;
                2'b01:queued<=queued-1;
                default:begin end
            endcase
            if(queued>max_queued) max_queued<=queued;
            if(m_valid && m_ready && m_rsp_valid && m_rsp_ready) refills<=refills+1;
            if(m_valid && m_ready && m_read) read_streak<=read_streak+1;else read_streak<=0;
            if(m_valid && m_ready && !m_read) write_streak<=write_streak+1;else write_streak<=0;
            if(read_streak>max_read_streak) max_read_streak<=read_streak;
            if(write_streak>max_write_streak) max_write_streak<=write_streak;
            if(m_valid && m_ready) begin
                if(m_addr<32'ha0010000 || m_addr>=32'ha0080000 || m_addr[1:0]!=0 || m_mask!=15) $fatal(1,"DMA range/mask");
                due[tail]<=cycles+(dma_mode==1 ? 1 : dma_mode==0 ? 1+cycles%3 : 3+cycles%5);
                response_data[tail]<=mem[m_addr[18:2]];tail<=!tail;
                if(!m_read) mem[m_addr[18:2]]<=m_wdata;
            end
            if(m_rsp_valid && m_rsp_ready) head<=!head;
        end
    end
    task automatic bus(input bit read_,input [19:0] addr,input [31:0] data,output [31:0] value);
        begin
            @(negedge clk);cmd_valid=1;cmd_read=read_;cmd_addr=addr;cmd_wdata=data;
            do @(posedge clk);while(!cmd_ready);
            @(negedge clk);cmd_valid=0;
            while(!rsp_valid) @(negedge clk);
            if(rsp_err) $fatal(1,"Register error %h data=%h",addr,data);
            value=rsp_rdata;
        end
    endtask
    task automatic execute;
        begin
            bus(0,0,1,rd);rd=1;polls=0;
            while(rd[0]) begin
                repeat(100) @(negedge clk);bus(1,4,0,rd);polls++;
                if(polls>20000 || rd[4:2]!=0) $fatal(1,"Execution failed status=%h state=%d",rd,dut.state);
            end
            if(!rd[1]) $fatal(1,"Missing completion");
            bus(1,'h40,0,counted_cycles);phase_sum=0;
            for(integer c=0;c<10;c++) begin bus(1,20'('h60+4*c),0,rd);phase_sum+=64'(rd);end
            if(phase_sum!=64'(counted_cycles)) $fatal(1,"Register phase accounting");
            bus(1,'h88,0,rd);if(rd!==dut.dma_request_wait) $fatal(1,"Request wait counter");
            bus(1,'h8c,0,rd);if(rd!==dut.dma_response_wait) $fatal(1,"Response wait counter");
            bus(1,'h90,0,rd);if(rd!==dut.dma_retire_refill) $fatal(1,"Retire/refill counter");
        end
    endtask
    initial begin
        if($value$plusargs("layers=%d",layers)) begin end
        if($value$plusargs("dma_mode=%d",dma_mode)) begin end
        if($value$plusargs("constant_edge=%d",constant_edge)) begin end
        if($value$plusargs("transport=%d",transport)) begin end
        repeat(4) @(negedge clk);rst_n=1;
        $readmemh("output/encoder-vectors/task_00/input.hex",initial_x);
        if(constant_edge) for(j=0;j<6336;j++) initial_x[j]=32'h80000000;
        for(j=0;j<6336;j++) mem[16384+j]=initial_x[j];
        bus(0,20'h20,32'ha0010000,rd);bus(0,20'h24,32'ha0050000,rd);
        bus(0,20'h28,32'ha0018000,rd);bus(0,20'h2c,32'ha0030000,rd);bus(0,20'h30,32'ha0064000,rd);
        for(li=0;li<layers;li++) begin
            folder=$sformatf("output/encoder-vectors/layer_%02d",li);
            $readmemh({folder,"/params.hex"},params);$readmemh({folder,"/config.hex"},cfg);
            if(constant_edge) begin
                for(j=0;j<16704;j++) params[j]=0;
                for(j=0;j<64;j++) begin params[16448+j]=65536;params[16576+j]=65536;end
            end
            for(j=0;j<16704;j++) mem[81920+j]=params[j];
            folder=$sformatf("output/encoder-vectors/task_00/layer_%02d",li);
            $readmemh({folder,"/ffn_input.hex"},packed_x);$readmemh({folder,"/expected.hex"},expected);
            $readmemh({folder,"/ffn.hex"},ffn_expected);
            if(constant_edge) begin
                for(j=0;j<6336;j++) begin expected[j]=0;ffn_expected[j]=0;end
                for(j=0;j<3168;j++) packed_x[j]=0;
            end
`ifdef ENCODER_TRACE
            $readmemh({folder,"/q.hex"},tq);$readmemh({folder,"/k.hex"},tk);$readmemh({folder,"/v.hex"},tv);
            $readmemh({folder,"/score.hex"},ts);$readmemh({folder,"/prob.hex"},tp);$readmemh({folder,"/context.hex"},tc);
            $readmemh({folder,"/attention.hex"},ta);$readmemh({folder,"/residual1.hex"},tr1);$readmemh({folder,"/z.hex"},tz);$readmemh({folder,"/residual2.hex"},tr2);
            if(constant_edge) begin
                for(j=0;j<6336;j++) begin tq[j]=0;tk[j]=0;tv[j]=0;tc[j]=0;ta[j]=0;tr1[j]=32'h80000000;tz[j]=0;tr2[j]=0;end
                for(j=0;j<9801;j++) begin ts[j]=0;tp[j]=32'd169466;end
            end
`endif
            bus(0,20'h34,cfg[1]|(li==0 ? 32'd0 : 32'd1)|(transport==2 ? 32'd8 : transport==1 ? 32'd4 : 32'd0),rd);bus(0,20'h38,0,rd);execute();
            for(j=0;j<3168;j++) if(mem[24576+j]!==packed_x[j]) $fatal(1,"Front mismatch layer=%0d word=%0d got=%h expected=%h",li,j,mem[24576+j],packed_x[j]);
            bus(1,20'h40,0,rd);$display("ENCODER_FRONT_PASS layer=%0d cycles=%0d",li,rd);$fflush();
            for(j=0;j<6336;j++) begin mem[49152+2*j]=ffn_expected[j][31:0];mem[49153+2*j]=ffn_expected[j][63:32];end
            if(transport==1) for(j=0;j<1584;j++) begin
                for(integer t=0;t<4;t++) packed_group[t*40+:40]=ffn_expected[j*4+t][39:0];
                for(integer t=0;t<5;t++) mem[49152+j*5+t]=packed_group[t*32+:32];
            end
            if(transport==2 && li==0) begin
                // Cancellation during a stalled stream invalidates resident Z.
                bus(0,20'h38,1,rd);bus(0,0,1,rd);
                repeat(12) @(negedge clk);link_abort_in=1;
                repeat(3) @(negedge clk);link_abort_in=0;
                bus(1,4,0,rd);
                if(rd[0] || !rd[2] || rd[6:5]!=0 || result_ready) $fatal(1,"Tail cancel validity");
                bus(0,20'h38,0,rd);execute();
            end
            stream_index=0;stream_feed=transport==2;
            bus(0,20'h38,1,rd);execute();stream_feed=0;
            if(transport==2 && stream_index!=6336) $fatal(1,"Tail stream length");
            for(j=0;j<6336;j++) if(mem[102400+j]!==expected[j]) $fatal(1,"Tail mismatch layer=%0d word=%0d got=%h expected=%h",li,j,mem[102400+j],expected[j]);
            bus(1,20'h40,0,rd);$display("ENCODER_TAIL_PASS layer=%0d cycles=%0d",li,rd);$fflush();
        end
        if(dma_mode==2 && (max_queued!=2 || refills==0)) $fatal(1,"Missing multi-outstanding coverage");
        if(dma_mode==1 && (max_read_streak<6336 || max_write_streak<6336)) $fatal(1,"DMA not continuous read=%0d write=%0d",max_read_streak,max_write_streak);
        $display("ENC_DMA_STREAM mode=%0d outstanding=%0d refill=%0d read_streak=%0d write_streak=%0d",dma_mode,max_queued,refills,max_read_streak,max_write_streak);
        $display("ENCODER_PASS layers=%0d constant_edge=%0d transport=%0d",layers,constant_edge,transport);$finish;
    end
endmodule
