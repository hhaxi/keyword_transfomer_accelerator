`timescale 1ns/1ps
`include "kwt_options.vh"
// A real two-entry ordered response queue, including simultaneous retire/refill.
module tb_dma_two_credit;
    reg clk=0;always #3.333 clk=~clk;
    reg rst_n=0,cmd_valid=0,cmd_read=0,rsp_ready=1;
    reg [19:0] cmd_addr=0;reg [31:0] cmd_wdata=0;reg [3:0] cmd_wmask=15;
    wire cmd_ready,rsp_valid,rsp_err;wire [31:0] rsp_rdata;
    wire m_valid,m_read,m_rsp_ready;wire [31:0] m_addr,m_wdata;wire [3:0] m_mask;
    reg head=0,tail=0;integer level=0,cycles=0,writes=0,dual=0,overlap=0;
    reg [31:0] queue_data[0:1];reg queue_error[0:1];integer delay_left[0:1];
    wire m_rsp_valid=level>0 && delay_left[head]==0;
    wire m_ready=(level<2 || (m_rsp_valid && m_rsp_ready)) && cycles%7!=0;
    wire [31:0] m_rdata=queue_data[head];wire m_err=queue_error[head];
    wire accept=m_valid && m_ready,retire=m_rsp_valid && m_rsp_ready;
    reg [31:0] mem[0:131071],x[0:3167],w[0:8191],b[0:255],rd;
    reg [63:0] expected[0:25343];integer j;reg inject=0,inject_x=0,held=0;reg [68:0] offer;
    kwt_ffn1_dma dut(.*);
    always @(posedge clk) begin
        cycles<=cycles+1;
        if(cycles>3000000) $fatal(1,"Two-credit timeout");
        if(!rst_n) begin head<=0;tail<=0;level<=0;held<=0;end
        else begin
            if(held && (!m_valid || offer!=={m_read,m_addr,m_wdata,m_mask})) $fatal(1,"Unstable two-credit offer");
            held<=m_valid && !m_ready;offer<={m_read,m_addr,m_wdata,m_mask};
            if(level==2) dual<=dual+1;
            if(accept && retire) overlap<=overlap+1;
            level<=level+int'(accept)-int'(retire);
            if(level>0 && delay_left[head]>0) delay_left[head]<=delay_left[head]-1;
            if(retire) head<=!head;
            if(accept) begin
                if(m_mask!=15 || m_addr[1:0]!=0 || m_addr<32'ha0010000 || m_addr>=32'ha0080000)
                    $fatal(1,"Unsafe queued DMA access");
                queue_data[tail]<=m_read ? mem[m_addr[18:2]] : 0;
                queue_error[tail]<=inject || (inject_x && m_read && m_addr==32'ha00100fc);inject<=0;
                if(inject_x && m_read && m_addr==32'ha00100fc) inject_x<=0;
                delay_left[tail]<=(m_addr==32'ha001007c || m_addr==32'ha00617fc) ? 40 : cycles%4;
                if(!m_read && !inject) begin mem[m_addr[18:2]]<=m_wdata;writes<=writes+1;end
                tail<=!tail;
            end
        end
    end
    task automatic control(input bit read_,input [19:0] address,input [31:0] data);
        begin
            @(negedge clk);cmd_valid=1;cmd_read=read_;cmd_addr=address;cmd_wdata=data;
            do @(posedge clk);while(!cmd_ready);
            @(negedge clk);cmd_valid=0;
            while(!rsp_valid) @(negedge clk);
            if(rsp_err) $fatal(1,"Unexpected control error");rd=rsp_rdata;
            @(negedge clk);
        end
    endtask
    task automatic idle(input [4:0] status);
        begin
            rd=1;while(rd[0]) control(1,4,0);
            if(rd[4:0]!==status || level!=0 || m_valid) $fatal(1,"Not drained/status %h",rd);
        end
    endtask
    initial begin
        $readmemh("vectors/task_02/x_packed.hex",x);$readmemh("vectors/task_02/w_packed.hex",w);
        $readmemh("vectors/task_02/b.hex",b);$readmemh("vectors/task_02/expected.hex",expected);
        for(j=0;j<3168;j=j+1) mem[16384+j]=x[j];
        for(j=0;j<8192;j=j+1) mem[24576+j]=w[j];
        for(j=0;j<256;j=j+1) mem[40960+j]=b[j];
        repeat(4) @(negedge clk);rst_n=1;
        control(0,20'h20,32'ha0010000);control(0,20'h24,32'ha0018000);
        control(0,20'h28,32'ha0028000);control(0,20'h2c,32'ha0030000);
        control(0,0,1);while(level!=2) @(negedge clk);control(0,0,2);idle(8);
        inject=1;control(0,0,1);idle(4);
        if(`KWT_SMALL_X) begin
            // Fault at row1's final X word while row0 is executing, then retry.
            inject_x=1;control(0,0,1);idle(4);
            if(inject_x) $fatal(1,"Missing streamed-X fault coverage");
            control(0,0,1);
            while(!(dut.phase==4 && level==2 && dut.read_received>=8480)) @(negedge clk);
            control(0,0,2);idle(8);
        end
        writes=0;control(0,0,1);idle(2);
        for(j=0;j<25344;j=j+1) if({mem[49152+2*j+1],mem[49152+2*j]}!==expected[j])
            $fatal(1,"Two-credit output mismatch %0d",j);
        if(writes!=50688 || dual==0 || overlap==0) $fatal(1,"Missing credit coverage writes=%0d dual=%0d overlap=%0d",writes,dual,overlap);
        $display("TWO_CREDIT_PASS queue-full=%0d simultaneous=%0d abort/error recovery exact outputs",dual,overlap);$finish;
    end
endmodule
