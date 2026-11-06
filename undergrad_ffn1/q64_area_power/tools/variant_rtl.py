"""Auditable transformations of the frozen q64_fused_pause core."""
def once(text,old,new):
    if text.count(old)!=1:raise ValueError('Reference template changed: '+old[:100])
    return text.replace(old,new)

def sequence_core(text):
    text=once(text,'reg [39:0] fifo[0:63];reg [14:0] indices[0:63];reg [5:0] head,tail;',
                   'reg [39:0] fifo[0:63];reg [5:0] head,tail;')
    text=once(text,'assign dma_out_index=indices[head];','''
 kwt_output_sequence sequence_gen(.clk(clk),.rst_n(rst_n),.clear(dma_clear || start),
   .advance(pop),.index(dma_out_index),.lane(),.last_lane());''')
    text=once(text,';indices[6\'(tail+(ri<<CL)+ci)]<=((row+ri)<<8)+col+ci;end',';end')
    return text

def bank_core(text,depth):
    text=once(text,'reg [39:0] fifo[0:63];reg [14:0] indices[0:63];reg [5:0] head,tail;\n reg [6:0] count;',
                   'wire queue_ready,queue_valid;wire [39:0] queue_value;wire [14:0] queue_index;')
    text=once(text,'wire pop=count!=0 && dma_out_ready;','wire pop=queue_valid && dma_out_ready;')
    text=once(text,'wire push=state==EMIT && count<=64-batch;','wire push=state==EMIT && queue_ready;')
    text=once(text,'assign dma_x_free=~x_valid;assign dma_out_valid=count!=0;assign dma_out_index=indices[head];\n assign dma_out_data={{24{fifo[head][39]}},fifo[head]};',
        '''wire [1279:0] group_values;
 genvar qr,qc;
 generate for(qr=0;qr<4;qr=qr+1)begin:queue_rows
 for(qc=0;qc<8;qc=qc+1)begin:queue_columns
   assign group_values[(qr*8+qc)*40+:40]=acc[qr][qc];
 end end endgenerate
 kwt_group_queue #(.DEPTH(%d)) result_queue(.clk(clk),.rst_n(rst_n),
   .clear(dma_clear || start),.in_valid(state==EMIT),.in_ready(queue_ready),.in_values(group_values),
   .out_valid(queue_valid),.out_ready(dma_out_ready),.out_value(queue_value),.out_index(queue_index));
 assign dma_x_free=~x_valid;assign dma_out_valid=queue_valid;assign dma_out_index=queue_index;
 assign dma_out_data={{24{queue_value[39]}},queue_value};'''%depth)
    text=text.replace('head<=0;tail<=0;count<=0;','')
    text=once(text,'case({push,pop})\n 2\'b10:count<=count+batch;2\'b01:count<=count-1;2\'b11:count<=count+batch-1;default:begin end endcase\n ','')
    text=once(text,"for(ri=0;ri<ROWS;ri=ri+1)for(ci=0;ci<COLS;ci=ci+1)if(row+ri<99)begin\n fifo[6'(tail+(ri<<CL)+ci)]<=acc[ri][ci];indices[6'(tail+(ri<<CL)+ci)]<=((row+ri)<<8)+col+ci;end\n tail<=tail+batch;",'')
    text=once(text,'if(pop)begin head<=head+1;popped<=popped+1;','if(pop)begin popped<=popped+1;')
    return text

def transform(text,design):
    if design.get('early_free'):
        text=once(text,'if(group_last)x_valid[tile_bank]<=0;', '')
        text=once(text,'if(state==LAST)state<=PRODUCT_PIPE ? PIPE : EMIT;',
            'if(state==LAST)begin\n state<=PRODUCT_PIPE ? PIPE : EMIT;\n'
            ' // The last old-tile operands have been consumed. Results stay in acc.\n'
            ' if(group_last)x_valid[tile_bank]<=0;\n end')
    if design['queue']=='sequence':text=sequence_core(text)
    elif design['queue'] in ('bank1','bank2'):text=bank_core(text,int(design['queue'][-1]))
    if design['queue']!='reference':
        text=once(text,' // Supported schedules',
            ' generate if(ROWS!=4 || COLS!=8 || KPAR!=2)begin:q64_only\n KWT_Q64_REQUIRED invalid_geometry();\n end endgenerate\n // Supported schedules')
    return text
