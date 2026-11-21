`timescale 1ns/1ps
module tb_gelu;
    reg signed [39:0] value;
    reg [4:0] input_shift,output_shift;
    wire signed [15:0] result;
    wire saturated;
    reg [15:0] expected;
    reg expected_sat;
    reg [39:0] scanned_value;
    reg [4:0] scanned_input_shift,scanned_output_shift;
    integer fd,n,count=0;
    kwt_gelu dut(.*);
    initial begin
        fd=$fopen("output/ffn-vectors/gelu-tests.txt","r");
        if(fd==0) $fatal(1,"Missing GELU reference vectors");
        while(!$feof(fd)) begin
            n=$fscanf(fd,"%h %h %h %h %h\n",scanned_value,scanned_input_shift,scanned_output_shift,expected,expected_sat);
            if(n==5) begin
                value=scanned_value;input_shift=scanned_input_shift;output_shift=scanned_output_shift;
                #1;
                if(result!==expected || saturated!==expected_sat)
                    $fatal(1,"GELU mismatch value=%h shifts=%0d,%0d actual=%h expected=%h sat=%b/%b",value,input_shift,output_shift,result,expected,saturated,expected_sat);
                count=count+1;
            end else if(n!=-1) $fatal(1,"Malformed GELU vector");
        end
        $fclose(fd);
        if(count<50000) $fatal(1,"Insufficient GELU checks");
        $display("GELU_PASS vectors=%0d",count);$finish;
    end
endmodule
