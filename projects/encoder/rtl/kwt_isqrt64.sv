module kwt_isqrt64(
    input wire clk,rst_n,clear,start,input wire [63:0] value,
    output reg busy,done,output reg [31:0] root
);
    reg [63:0] shift_;reg [63:0] remainder;reg [5:0] count;
    wire [65:0] trial={remainder[63:0],shift_[63:62]};
    wire [65:0] subtrahend={32'd0,root,2'b01};
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin busy<=0;done<=0;root<=0;shift_<=0;remainder<=0;count<=0;end
        else if(clear) begin busy<=0;done<=0;end
        else begin
            done<=0;
            if(start && !busy) begin busy<=1;root<=0;shift_<=value;remainder<=0;count<=0;end
            else if(busy) begin
                remainder<=64'(trial>=subtrahend ? trial-subtrahend : trial);
                root<={root[30:0],trial>=subtrahend};shift_<={shift_[61:0],2'b0};count<=count+1'b1;
                if(count==31) begin busy<=0;done<=1;end
            end
        end
    end
endmodule
