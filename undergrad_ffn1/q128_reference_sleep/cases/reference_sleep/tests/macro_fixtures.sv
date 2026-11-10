// Independently written interface fixtures. NOT the ARM/foundry model.
// No timing, collision, retention or power signoff coverage is claimed.
module fixture_sp #(parameter AW=7)(
    output reg [15:0] Q,
    input CLK,CEN,input [15:0] WEN,input [AW-1:0] A,
    input [15:0] D,input [2:0] EMA,input [1:0] EMAW,input GWEN,RET1N
);
    reg [15:0] mem[0:(1<<AW)-1];
`ifdef KWT_TEST_INVENTORY
    initial case(AW)
        7: tb_top_inventory.n128=tb_top_inventory.n128+1;
        10: tb_top_inventory.n1024=tb_top_inventory.n1024+1;
        12: tb_top_inventory.n4096=tb_top_inventory.n4096+1;
    endcase
`endif
`ifdef KWT_TEST_SOC_INVENTORY
    initial case(AW)
        7: tb_soc_inventory.n128=tb_soc_inventory.n128+1;
        10: tb_soc_inventory.n1024=tb_soc_inventory.n1024+1;
        12: tb_soc_inventory.n4096=tb_soc_inventory.n4096+1;
    endcase
`endif
    always @(posedge CLK) if(!CEN) begin
        if(!RET1N) $fatal(1,"access during retention");
        if(!GWEN) begin
            for(integer b=0;b<16;b=b+1) if(!WEN[b]) mem[A][b]<=D[b];
        end else Q<=mem[A];
    end
endmodule
`define FIXTURE(NAME,BITS_A) \
module NAME(output wire [15:0] Q,input CLK,CEN,input [15:0] WEN, \
 input [BITS_A-1:0] A,input [15:0] D,input [2:0] EMA,input [1:0] EMAW, \
 input GWEN,RET1N); fixture_sp #(.AW(BITS_A)) model(.*); endmodule
`FIXTURE(RAMSP128X16,7)
`FIXTURE(RAMSP1024X16,10)
`FIXTURE(RAMSP4096X16,12)
`undef FIXTURE
