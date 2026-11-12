// Iterative integer arithmetic. No combinational division or square-root IP.
module kwt_udiv64 #(parameter SKIP_LEADING=0)(
    input wire clk,rst_n,clear,start,input wire [63:0] numerator,
    input wire [31:0] denominator,output reg busy,done,output reg [63:0] quotient
);
    reg [63:0] shift_;reg [31:0] remainder;
    reg [31:0] divisor;reg [6:0] count;
    wire [32:0] trial={remainder[31:0],shift_[63]};
    // Seed the remainder after a prefix whose quotient bits are all zero.
    // The bounds are checked here so small divisors retain the full division.
    wire skip_exp=SKIP_LEADING!=0 && numerator==64'h1000000000000 && denominator>=32'h1000000;
    wire skip_norm=SKIP_LEADING!=0 && numerator==64'h1000000000 && denominator>=32'd64;
    wire take_bit=trial>={1'b0,divisor};
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin busy<=0;done<=0;quotient<=0;shift_<=0;remainder<=0;divisor<=0;count<=0;end
        else if(clear) begin busy<=0;done<=0;end
        else begin
            done<=0;
            if(start && !busy) begin
                busy<=1;divisor<=denominator;
                shift_<=skip_exp || skip_norm ? 64'd0 : numerator;
                remainder<=skip_exp ? 32'h800000 : skip_norm ? 32'd32 : 32'd0;
                count<=skip_exp ? 7'd39 : skip_norm ? 7'd33 : 7'd0;
            end
            else if(busy) begin
                remainder<=32'(take_bit ? trial-{1'b0,divisor} : trial);
                shift_<={shift_[62:0],take_bit};
                count<=count+1'b1;
                if(count==63) begin busy<=0;done<=1;quotient<={shift_[62:0],take_bit};end
            end
        end
    end
endmodule
