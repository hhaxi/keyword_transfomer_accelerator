module kwt_sram16 #(parameter AW=12)(
 input wire clk,cs,we,input wire [AW-1:0] addr,input wire [15:0] din,output wire [15:0] dout);
 wire cen=~cs,gwen=~we;
 generate
 if (AW<=7) begin: native128
 wire [6:0] a={{7-AW{1'b0}},addr};
 RAMSP128X16 memory(.Q(dout),.CLK(clk),.CEN(cen),.WEN(16'b0),.A(a),.D(din),
 .EMA(3'b000),.EMAW(2'b00),.GWEN(gwen),.RET1N(1'b1));
 end
 if (AW>7 && AW<=10) begin: native1024
 wire [9:0] a={{10-AW{1'b0}},addr};
 RAMSP1024X16 memory(.Q(dout),.CLK(clk),.CEN(cen),.WEN(16'b0),.A(a),.D(din),
 .EMA(3'b000),.EMAW(2'b00),.GWEN(gwen),.RET1N(1'b1));
 end
 if (AW>10 && AW<=12) begin: native4096
 wire [11:0] a={{12-AW{1'b0}},addr};
 RAMSP4096X16 memory(.Q(dout),.CLK(clk),.CEN(cen),.WEN(16'b0),.A(a),.D(din),
 .EMA(3'b000),.EMAW(2'b00),.GWEN(gwen),.RET1N(1'b1));
 end
 if (AW>12 || AW<1) begin: unsupported
 KWT_UNSUPPORTED_SRAM_ADDRESS_WIDTH invalid_configuration();
 end
 endgenerate
endmodule
