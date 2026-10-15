// Iterative integer arithmetic. No combinational division or square-root IP.
module kwt_udiv64(
    input wire clk,rst_n,clear,start,input wire [63:0] numerator,
    input wire [31:0] denominator,output reg busy,done,output reg [63:0] quotient
);
    reg [63:0] shift_;reg [31:0] remainder;
    reg [31:0] divisor;reg [6:0] count;
    wire [32:0] trial={remainder[31:0],shift_[63]};
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin busy<=0;done<=0;quotient<=0;shift_<=0;remainder<=0;divisor<=0;count<=0;end
        else if(clear) begin busy<=0;done<=0;end
        else begin
            done<=0;
            if(start && !busy) begin busy<=1;shift_<=numerator;remainder<=0;divisor<=denominator;count<=0;end
            else if(busy) begin
                remainder<=32'(trial>={1'b0,divisor} ? trial-{1'b0,divisor} : trial);
                shift_<={shift_[62:0],trial>={1'b0,divisor}};
                count<=count+1'b1;
                if(count==63) begin busy<=0;done<=1;quotient<={shift_[62:0],trial>={1'b0,divisor}};end
            end
        end
    end
endmodule
