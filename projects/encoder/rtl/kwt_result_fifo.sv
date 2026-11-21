// Four exact int40 FFN results. Payload unreset; clear invalidates both ends.
module kwt_result_fifo #(parameter WIDTH=40)(
    input wire clk,rst_n,clear,
    input wire in_valid,output wire in_ready,input wire [WIDTH-1:0] in_data,
    output wire out_valid,input wire out_ready,output wire [WIDTH-1:0] out_data
);
    reg [WIDTH-1:0] data[0:3];
    reg [1:0] head,tail;
    reg [2:0] count;
    assign out_valid=count!=0 && !clear;
    wire pop=out_valid && out_ready;
    assign in_ready=(count<4 || pop) && !clear;
    wire push=in_valid && in_ready;
    assign out_data=data[head];
    always @(posedge clk) if(push) data[tail]<=in_data;
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin head<=0;tail<=0;count<=0;end
        else if(clear) begin head<=0;tail<=0;count<=0;end
        else begin
            if(push) tail<=tail+1'b1;
            if(pop) head<=head+1'b1;
            case({push,pop})
                2'b10:count<=count+1'b1;
                2'b01:count<=count-1'b1;
                default:begin end
            endcase
        end
    end
endmodule
