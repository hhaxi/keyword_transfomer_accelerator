"""Guarded, single-factor transformations of frozen q64_bank1_fmt1 RTL."""
def once(text,old,new):
 if text.count(old)!=1:raise ValueError('Frozen template mismatch: '+old[:120])
 return text.replace(old,new)

def result_queue(text):
 text=once(text,'   reg [39:0] values[0:31];','''   reg [39:0] values[0:31];
   wire [3:0] payload_clk;
   for(genvar cg=0;cg<4;cg=cg+1)begin:clock_groups
     kwt_clock_gate u_gate(.clk(clk),.en(publish && write_bank==b),
       .test_en(1'b0),.gclk(payload_clk[cg]));
   end''')
 return once(text,'always @(posedge clk)\n       if(publish',
                  'always @(posedge payload_clk[j/8])\n       if(publish')

def mac_core(text):
 text=once(text,' genvar t,r,c,p,d;',''' wire [ROWS-1:0] mac_clk;
 genvar cg_row;
 generate for(cg_row=0;cg_row<ROWS;cg_row=cg_row+1)begin:mac_clock_groups
   kwt_clock_gate u_gate(.clk(clk),.en(product_valid || dma_clear || start),
     .test_en(1'b0),.gclk(mac_clk[cg_row]));
 end
 if(PRODUCT_PIPE!=0)begin:cg_requires_direct_mac
   KWT_CLOCK_GATING_REQUIRES_DIRECT_MAC invalid_configuration();
 end endgenerate
 genvar t,r,c,p,d;''')
 return once(text,'pe(.clk(clk),.rst_n(rst_n),.clear(dma_clear || start)',
                  'pe(.clk(mac_clk[r]),.rst_n(rst_n),.clear(dma_clear || start)')

def formatter(text):
 marker=' always @(posedge clk or negedge rst_n) begin'
 gated=''' // Only data storage is gated; queue/control handshakes keep root clk.
 wire [2:0] partial_clk;
 genvar slice,bank;
 generate for(slice=0;slice<3;slice=slice+1)begin:partial_groups
   kwt_clock_gate u_gate(.clk(clk),.test_en(1'b0),
     .en(clear || (take && index_ok && PACKED40 && gathered==slice)),
     .gclk(partial_clk[slice]));
   always @(posedge partial_clk[slice] or negedge rst_n)begin
     if(!rst_n)partial[slice*40+:40]<=0;
     else if(clear)partial[slice*40+:40]<=0;
     else if(take && index_ok && PACKED40 && gathered==slice)
       partial[slice*40+:40]<=in_data;
   end
 end
 for(bank=0;bank<DEPTH;bank=bank+1)begin:completed_groups
   wire payload_clk;
   kwt_clock_gate u_gate(.clk(clk),.test_en(1'b0),
     .en(clear || (publish && tail==bank)),.gclk(payload_clk));
   always @(posedge payload_clk or negedge rst_n)begin
     if(!rst_n)begin payload[bank]<=0;address[bank]<=0;end
     else if(clear)begin payload[bank]<=0;address[bank]<=0;end
     else if(publish && tail==bank)begin
       if(!PACKED40)begin
         payload[bank]<={96'b0,{24{in_data[39]}},in_data};
         address[bank]<={in_index,1'b0};
       end else begin
         payload[bank]<={in_data,partial};
         address[bank]<=({3'b0,first_index[14:2]}<<2)+{3'b0,first_index[14:2]};
       end
     end
   end
 end endgenerate
 always @(posedge partial_clk[0] or negedge rst_n)begin
   if(!rst_n)first_index<=0;
   else if(clear)first_index<=0;
   else if(take && index_ok && PACKED40 && gathered==0)first_index<=in_index;
 end
'''
 text=text.replace('partial<=0; gathered<=0; first_index<=0;', 'gathered<=0;')
 text=text.replace('     for(entry=0;entry<DEPTH;entry=entry+1) begin payload[entry]<=0; address[entry]<=0; end\n','')
 for line in ["         payload[tail]<={96'b0,{24{in_data[39]}},in_data};\n",
              "         address[tail]<={in_index,1'b0};\n",
              '         payload[tail]<={in_data,partial};\n',
              "         address[tail]<=({3'b0,first_index[14:2]}<<2)+{3'b0,first_index[14:2]};\n",
              '         partial[gathered*40 +: 40]<=in_data;\n',
              '         if (gathered==0) first_index<=in_index;\n']:
  text=once(text,line,'')
 return once(text,marker,gated+'\n'+marker)
