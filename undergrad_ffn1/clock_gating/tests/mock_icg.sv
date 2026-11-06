// Flow test fixture only. Never included in a candidate synthesis filelist.
module ICG_SMALL(input wire CK,E,TE,output wire Q);
 reg enabled;
 always_latch if(!CK)enabled=E|TE;
 assign Q=CK & enabled;
endmodule
