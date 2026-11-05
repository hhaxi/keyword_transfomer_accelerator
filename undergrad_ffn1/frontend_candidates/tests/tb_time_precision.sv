`timescale 1ns/1fs
module tb_time_precision;
 kwt_measure_fs clock_fs();
 initial begin
   #3.333333;
   if(clock_fs.now_fs()!=3333333) $fatal(1,"First edge lost precision");
   #3.333334;
   if(clock_fs.now_fs()!=6666667) $fatal(1,"Second edge lost precision");
   $display("TIME_PRECISION_PASS time_fs=%0d",clock_fs.now_fs());
   $finish;
 end
endmodule
module kwt_measure_fs;
 timeunit 1fs;
 timeprecision 1fs;
 function automatic time now_fs();
   now_fs=$time;
 endfunction
endmodule
