// Attention/PostNorm companion to the unchanged full-FFN DMA engine.
// Command 0: Q/K/V -> row Softmax -> PV -> O -> residual -> LN1 -> packed FFN input.
// Command 1: FFN result -> residual -> LN2 -> resident next-layer input / final DMA.
// E203 supplies commands/addresses only; all encoder arithmetic is hardware.
module kwt_encoder #(parameter STREAM_ENABLE=0, parameter PROJECTION_K4=0, parameter ATTENTION_K16=0)(
    input wire clk,rst_n,
    input wire cmd_valid,output wire cmd_ready,input wire [19:0] cmd_addr,
    input wire cmd_read,input wire [31:0] cmd_wdata,input wire [3:0] cmd_wmask,
    output reg rsp_valid,input wire rsp_ready,output reg [31:0] rsp_rdata,output reg rsp_err,
    output wire m_valid,input wire m_ready,output wire [31:0] m_addr,m_wdata,
    output wire m_read,output wire [3:0] m_mask,input wire m_rsp_valid,
    output wire m_rsp_ready,input wire [31:0] m_rdata,input wire m_err,
    input wire result_valid,output wire result_ready,input wire [39:0] result_data,
    output wire preload_permit,
    output wire input_valid,input wire input_ready,output wire [31:0] input_data,
    input wire link_abort_in,output wire link_abort_out
);
    localparam IDLE=0,LREQ=1,LWAIT=2,PINIT=3,PPRIME=4,PMAC=5,PSAVE=6,RSAVE=7,
        SINIT=8,SPRIME=9,SMAC=10,SSAVE=11,EREAD=12,ECALC=13,EDIV=14,EDWAIT=15,
        NREAD=16,NCALC=17,VINIT=18,VPRIME=19,VMAC=20,VSAVE=21,
        SUMINIT=22,SUMPRIME=23,SUMMAC=24,MEAN=25,VARPRIME=26,VARMAC=27,
        SQSTART=28,SQWAIT=29,NDIV=30,NDWAIT=31,APRIME=32,ANORM=33,AFFINE=34,
        DREAD=35,DCAP=36,WREQ=37,WWAIT=38,TGROUP=39,TREQ=40,TWAIT=41,TSTORE=42,TUNPACK=43,TSTREAM=44,
        PFLUSH=45,SFLUSH=46,SDRAIN=47,VFLUSH=48,PFLUSH2=49,PFLUSH3=50,
        SUMFLUSH=51,VARFLUSH=52,ANORM_MUL=53,AFFINE_ROUND=54,AFFINE_WRITE=55;
    localparam WIDE_PROJECTION=PROJECTION_K4>1;
    localparam PROJECTION_K=WIDE_PROJECTION ? 16 : PROJECTION_K4!=0 ? 4 : 1;
    localparam ATTENTION_LANES=ATTENTION_K16>1 ? 32 : 16;
    localparam ATTENTION_GROUPS=ATTENTION_LANES/4;
    localparam PIPELINED_SCORE=ATTENTION_K16>1;
    reg [5:0] state;
    reg [31:0] xbase,pbase,fxbase,fybase,ybase,config_,operation;
    reg done,error,aborted,config_error,abort_pending,resident_valid,z_valid,norm_second;
    reg [1:0] load_kind,projection;
    reg [13:0] load_index,tail_index;
    reg [10:0] dump_group;
    reg [1:0] dump_prefetch;
    reg [6:0] row,keyrow,k;
    reg [7:0] score_issue;
    reg [5:0] score_pipe,score_odd;
    wire score_fetch=PIPELINED_SCORE && (state==SPRIME || state==SMAC) && score_issue<198;
    wire score_retire=PIPELINED_SCORE && state==SMAC && score_pipe[5] && score_odd[5];
    wire signed [71:0] pipelined_score;
    reg [6:0] soft_issue;
    reg [5:0] soft_pipe;
    reg [32:0] soft_delta;
    reg signed [63:0] soft_prob_product;
    wire soft_fetch=PIPELINED_SCORE && (state==EREAD || state==ECALC ||
        state==NREAD || state==NCALC) && soft_issue<99;
    wire exp_retire=state==ECALC && (!PIPELINED_SCORE || soft_pipe[5]);
    wire prob_retire=state==NCALC && (!PIPELINED_SCORE || soft_pipe[1]);
    reg [3:0] group_;
    reg signed [71:0] acc[0:3];
    reg signed [31:0] row_max;
    reg signed [39:0] sum,mean;
    reg signed [39:0] sum_partial;
    reg [1:0] norm_flush;
    reg [31:0] exp_sum,reciprocal,low_word;
    reg [127:0] output_buffer,norm_value,gamma;
    reg [159:0] compact_buffer;
    reg [2:0] compact_word;
    wire compact_mode=config_[2];
    wire input_mode=STREAM_ENABLE!=0 && config_[4];
    wire stream_mode=STREAM_ENABLE!=0 && config_[3];
    reg [31:0] cycles,mac_cycles,read_commands,write_commands,sram_reads,sram_writes,saturations;
    // Phase counters are disjoint; wait counters overlap their DMA phase.
    reg [31:0] phase_cycles[0:9];
    reg [31:0] dma_request_wait,dma_response_wait,dma_retire_refill;
    reg [13:0] issue_index;
    reg [1:0] pending_count;
    reg offer_held,dma_error_pending;
    wire busy=state!=IDLE;
    wire take=cmd_valid && cmd_ready;
    wire wr=take && !cmd_read && cmd_wmask==15 && cmd_addr[1:0]==0;
    wire abort_now=wr && cmd_addr==0 && cmd_wdata==2;
    wire stopping=abort_pending || abort_now || dma_error_pending || (stream_mode && link_abort_in);
    wire retire=m_rsp_valid && pending_count!=0;
    // A front command may be idle while its peer still computes/holds results.
    assign link_abort_out=stream_mode && ((busy && (abort_now || abort_pending || dma_error_pending || (retire && m_err))) ||
        (input_mode && z_valid && abort_now));
    assign result_ready=state==TSTREAM && !stopping;
    wire result_fire=result_valid && result_ready;
    assign cmd_ready=!rsp_valid || rsp_ready;
    wire loading=state==LREQ || state==LWAIT;
    assign preload_permit=!loading;
    wire dumping=state==WREQ || state==WWAIT;
    wire input_dump=input_mode && dumping && !norm_second;
    assign input_valid=input_dump && issue_index<3168 && !stopping;
    assign input_data=output_buffer[issue_index[0]*32+:32];
    wire input_fire=input_valid && input_ready;
    wire tail_loading=state==TREQ || state==TWAIT;
    wire [13:0] load_length=load_kind==0 ? 14'd6336 : load_kind==1 ? 14'd320 : 14'd4096;
    wire [13:0] burst_length=loading ? load_length : tail_loading ? (compact_mode ? 14'd5 : 14'd8) : norm_second ? 14'd6336 : 14'd3168;
    // Two in-order credits allow retirement/refill every clock. A stalled offer
    // is irrevocable, including on abort/error; all accepted requests drain.
    assign m_valid=(loading || (dumping && !input_dump) || tail_loading) && issue_index<burst_length &&
        pending_count<2 && (!(abort_pending || dma_error_pending) || offer_held);
    wire issue=m_valid && m_ready;
    wire dump_fire=input_dump ? input_fire : issue;
    wire [2:0] pending_next={1'b0,pending_count}+{2'd0,issue}-{2'd0,retire};
    assign m_read=state!=WREQ && state!=WWAIT;
    assign m_mask=4'hf;
    assign m_rsp_ready=1'b1;
    wire [31:0] load_base=load_kind==0 ? xbase : load_kind==1 ? pbase+32'd65536 : pbase+{16'b0,projection,14'b0};
    assign m_addr=(state==TREQ || state==TWAIT) ? fybase+(compact_mode ? ({21'd0,tail_index[13:3]}<<4)+({21'd0,tail_index[13:3]}<<2) : {16'd0,tail_index[13:3],3'd0,2'b0})+{16'd0,issue_index,2'b0} :
        (state==WREQ || state==WWAIT) ?
            (norm_second ? ybase : fxbase)+{16'd0,issue_index,2'b0} :
            load_base+{16'd0,issue_index,2'b0};
    wire [1:0] write_lane=norm_second ? issue_index[1:0] : {1'b0,issue_index[0]};
    assign m_wdata=m_read ? 32'd0 : output_buffer[write_lane*32+:32];

    function automatic signed [71:0] sx32(input signed [31:0] v);
        sx32={{40{v[31]}},v};
    endfunction
    function automatic signed [71:0] sx64(input signed [63:0] v);
        sx64={{8{v[63]}},v};
    endfunction
    function automatic signed [71:0] rne(input signed [71:0] v,input [5:0] shift_);
        reg signed [71:0] q;
        reg [71:0] rem_,half_;
        begin
            if(shift_==0) rne=v;
            else begin
                // With floor(v/2**shift) the discarded bits are a nonnegative
                // remainder even for negative v. Ties select the even integer.
                q=v>>>shift_;rem_=$unsigned(v)&((72'd1<<shift_)-1'b1);half_=72'd1<<(shift_-1'b1);
                if(rem_>half_ || (rem_==half_ && q[0])) q=q+1'b1;
                rne=q;
            end
        end
    endfunction
    function automatic signed [31:0] clip32(input signed [71:0] v);
        begin
            if(v>72'sd2147483647) clip32=32'sh7fffffff;
            else if(v< -72'sd2147483648) clip32=32'sh80000000;
            else clip32=v[31:0];
        end
    endfunction
    function automatic [15:0] clip16(input signed [71:0] v);
        begin
            if(v>32767) clip16=16'h7fff;
            else if(v< -32768) clip16=16'h8000;
            else clip16=v[15:0];
        end
    endfunction
    function automatic overflow32(input signed [71:0] v);
        overflow32=v>72'sd2147483647 || v< -72'sd2147483648;
    endfunction
    function automatic [3:0] pop4(input [3:0] v);
        pop4={3'd0,v[0]}+{3'd0,v[1]}+{3'd0,v[2]}+{3'd0,v[3]};
    endfunction
    function automatic range_ok(input [31:0] base,input [31:0] bytes_);
        range_ok=base[1:0]==0 && base>=32'ha0010000 && base<=32'ha0080000-bytes_;
    endfunction
    wire addresses_ok=operation<=1 && (!config_[4] || config_[3]) && (config_&32'hffe0e0e0)==0 && (!config_[3] || STREAM_ENABLE!=0) && !(config_[2] && config_[3]) &&
        range_ok(xbase,25344) && range_ok(pbase,66816) && range_ok(fxbase,12672) &&
        range_ok(fybase,compact_mode ? 31680 : 50688) && range_ok(ybase,25344) &&
        (fxbase+12672<=pbase || pbase+66816<=fxbase) &&
        (fxbase+12672<=fybase || fybase+50688<=fxbase) &&
        (ybase+25344<=pbase || pbase+66816<=ybase) &&
        (ybase+25344<=fybase || fybase+50688<=ybase);

    reg xcs,xwe,qcs,qwe,kcs,kwe,vcs,vwe,wcs,wwe,pcs,pwe,scs,swe;
    reg [3:0] xm,qm,km,vm,wm,pm;
    reg [10:0] xa,qa,ka,va;reg [9:0] wa;reg [6:0] pa,sa;
    reg [127:0] xi,qi,ki,vi,wi,pi;reg [31:0] si;
    wire [127:0] xd,qd,kd,vd,wd,pd;wire [31:0] sd;
    wire [63:0] packed_dump;
    wire [127:0] dump_value=norm_second ? xd : {64'd0,packed_dump};
    genvar dump_lane;
    generate for(dump_lane=0;dump_lane<4;dump_lane=dump_lane+1) begin: dump_pack
        assign packed_dump[dump_lane*16+:16]=
            clip16(rne(sx32($signed(xd[dump_lane*32+:32])),{1'b0,config_[12:8]}));
    end endgenerate
    wire projection_read=state==PPRIME || state==PMAC ||
        ((state==PSAVE || state==RSAVE) && (group_!=15 || row!=98));
    wire x_wide=WIDE_PROJECTION && projection_read && projection!=3 && !xwe;
    wire [511:0] wide_x;
    if(WIDE_PROJECTION) begin: projection_input_mem
        kwt_attention_mem xm_(clk,xcs,xwe,x_wide,xm,xa,xi,512'd0,xd,wide_x);
    end else begin: narrow_input_mem
        kwt_vecmem32 #(.AW(11)) xm_(clk,xcs,xwe,xm,xa,xi,xd);
        assign wide_x=0;
    end
    wire [32*ATTENTION_LANES-1:0] wide_q,wide_k,wide_v,context_words;
    wire [ATTENTION_LANES-1:0] context_overflows;
    wire score_read=state==SPRIME || state==SMAC || state==SSAVE;
    wire value_read=state==VPRIME || state==VMAC || state==VSAVE;
    wire q_wide=ATTENTION_K16!=0 && (score_read || state==VSAVE ||
        (WIDE_PROJECTION && projection_read && projection==3));
    wire k_wide=ATTENTION_K16!=0 && score_read;
    wire v_wide=ATTENTION_K16!=0 && value_read;
    generate if(ATTENTION_K16!=0) begin: wide_attention_mem
        kwt_attention_mem #(.BANKS(ATTENTION_GROUPS)) qm_(clk,qcs,qwe,q_wide,qm,qa,qi,context_words,qd,wide_q);
        kwt_attention_mem #(.BANKS(ATTENTION_GROUPS)) km_(clk,kcs,kwe,k_wide,km,ka,ki,{32*ATTENTION_LANES{1'b0}},kd,wide_k);
        kwt_attention_mem #(.BANKS(ATTENTION_GROUPS)) vm_(clk,vcs,vwe,v_wide,vm,va,vi,{32*ATTENTION_LANES{1'b0}},vd,wide_v);
    end else begin: narrow_attention_mem
        kwt_vecmem32 #(.AW(11)) qm_(clk,qcs,qwe,qm,qa,qi,qd);
        kwt_vecmem32 #(.AW(11)) km_(clk,kcs,kwe,km,ka,ki,kd);
        kwt_vecmem32 #(.AW(11)) vm_(clk,vcs,vwe,vm,va,vi,vd);
        assign wide_q=0;assign wide_k=0;assign wide_v=0;
    end endgenerate
    wire [128*PROJECTION_K-1:0] wide_weights;
    genvar weight_bank;
    generate if (PROJECTION_K4 != 0) begin: wide_projection
        localparam BANKS=4*PROJECTION_K, BITS=$clog2(BANKS);
        wire [11-BITS:0] weight_address = wwe ? load_index[11:BITS] : wa[9:BITS-2];
        for (weight_bank=0; weight_bank<BANKS; weight_bank=weight_bank+1) begin: banks
          if (!WIDE_PROJECTION) begin: macro_banks
            wire [31:0] words [0:1];
            reg read_bank;
            always @(posedge clk) if(wcs && !wwe) read_bank<=weight_address[7];
            for(genvar page=0;page<2;page=page+1) begin: pages
                wire select=wcs && weight_address[7]==page && (!wwe || load_index[3:0]==weight_bank);
                for(genvar half=0;half<2;half=half+1) begin: halves
                    kwt_sram16 #(.AW(7)) macro_(.clk(clk),.cs(select),.we(wwe),
                        .addr(weight_address[6:0]),.din(m_rdata[16*half+:16]),.dout(words[page][16*half+:16]));
                end
            end
            assign wide_weights[weight_bank*32+:32]=words[read_bank];
          end else begin: fpga_wide
            (* ram_style = "block" *) reg [31:0] weights [0:(4096/BANKS)-1];
            reg [31:0] read_data;
            always @(posedge clk) if (wcs) begin
                if (!wwe) read_data <= weights[weight_address];
                else if (load_index[BITS-1:0] == weight_bank)
                    weights[weight_address] <= m_rdata;
            end
            assign wide_weights[weight_bank*32+:32] = read_data;
          end
        end
        assign wd=wide_weights[127:0];
    end else begin: scalar_projection
        kwt_vecmem32 #(.AW(10)) wm_(clk,wcs,wwe,wm,wa,wi,wd);
        assign wide_weights=0;
    end endgenerate
    kwt_vecmem32 #(.AW(7)) pm_(clk,pcs,pwe,pm,pa,pi,pd);
    if(PIPELINED_SCORE) begin: dual_port_score
        reg [31:0] scores[0:127];
        reg [31:0] data;
        always @(posedge clk) begin
            if(scs && swe) scores[sa]<=si;
            if(soft_fetch && !stopping) data<=scores[soft_issue];
            else if(scs && !swe) data<=scores[sa];
        end
        assign sd=data;
    end else begin: single_port_score
        kwt_sram16 #(.AW(7)) score_lo(clk,scs,swe,sa,si[15:0],sd[15:0]);
        kwt_sram16 #(.AW(7)) score_hi(clk,scs,swe,sa,si[31:16],sd[31:16]);
    end
    wire another_group=group_!=15 || row!=98;
    wire [6:0] following_row=group_==15 ? row+1'b1 : row;
    wire [3:0] following_group=group_+1'b1;
    wire [6:0] next_k=k+1'b1;
    wire [6:0] read_k=(state==PPRIME || state==SPRIME || state==VPRIME) ? 7'd0 : next_k;
    wire [3:0] score_read_k=ATTENTION_K16!=0 ?
        (state==SPRIME ? 4'd0 : k[3:0]+4'(ATTENTION_GROUPS)) : read_k[3:0];
    localparam [6:0] SCORE_LAST_K=ATTENTION_K16!=0 ? 7'(16-ATTENTION_GROUPS) : 7'd15;
    localparam [3:0] VALUE_LAST_GROUP=ATTENTION_K16!=0 ? 4'(16-ATTENTION_GROUPS) : 4'd15;
    wire [3:0] following_value_group=group_+(ATTENTION_K16!=0 ? 4'(ATTENTION_GROUPS) : 4'd1);
    wire [5:0] projection_read_k = state==PPRIME ? 6'd0 :
        (PROJECTION_K4 != 0 ? k[5:0] + 6'(PROJECTION_K) : read_k[5:0]);
    localparam [6:0] PROJECTION_LAST_K = 7'(64-PROJECTION_K);
    wire [3:0] next_group=group_+1'b1;
    wire [3:0] read_group=(state==SUMPRIME || state==VARPRIME) ? 4'd0 : next_group;
    wire [127:0] projection_input=projection==3 ? qd : xd;
    wire [511:0] projection_context;
    if(ATTENTION_LANES==32)
        assign projection_context=k[4] ? wide_q[1023:512] : wide_q[511:0];
    else assign projection_context=wide_q;
    wire [511:0] wide_projection_input=projection==3 ? projection_context : wide_x;
    wire signed [31:0] scalar_input=PROJECTION_K4 != 0 ?
        projection_input[31:0] : projection_input[k[1:0]*32+:32];
    wire signed [32:0] delta=$signed({row_max[31],row_max})-$signed({sd[31],sd});
    wire [31:0] exponential;
    kwt_exp_negative_core #(.PIPELINE(PIPELINED_SCORE)) exp_unit(
        .clk(clk),.delta(PIPELINED_SCORE ? soft_delta : delta),.result(exponential));

    reg signed [31:0] lhs[0:3],rhs[0:3];
    wire signed [63:0] product[0:3];
    wire signed [31:0] centered[0:3];
    wire signed [71:0] projected[0:3],affine_value[0:3];
    wire signed [71:0] projection_partial[0:3];
    reg signed [31:0] norm_centered[0:3];
    reg signed [63:0] norm_product[0:3];
    reg signed [71:0] affine_stage[0:3],variance_pair[0:1],variance_partial;
    genvar l;
    generate for(l=0;l<4;l=l+1) begin: arithmetic
        assign product[l]=lhs[l]*rhs[l];
        assign centered[l]=clip32(sx32($signed(xd[l*32+:32]))-{{32{mean[39]}},mean});
        assign projected[l]=rne(acc[l],6'd16);
        if(PIPELINED_SCORE) begin: norm_pipeline
            assign affine_value[l]=affine_stage[l];
            always @(posedge clk) begin
                if(state==VARMAC || state==ANORM) norm_centered[l]<=centered[l];
                if(state==VARMAC || state==VARFLUSH || state==AFFINE) norm_product[l]<=product[l];
                if(state==AFFINE_ROUND) affine_stage[l]<=
                    rne(sx64(norm_product[l]),6'd16)+sx32($signed(pd[l*32+:32]));
            end
        end else begin: norm_combinational
            assign affine_value[l]=rne(sx64(product[l]),6'd16)+sx32($signed(pd[l*32+:32]));
        end
        if (WIDE_PROJECTION) begin: pipeline_projection
            reg signed [63:0] term[0:15];
            reg signed [65:0] quarter[0:3];
            reg signed [67:0] partial;
            for(genvar p=0;p<16;p=p+1) begin: products
                always @(posedge clk) if(state==PMAC)
                    term[p]<=$signed(wide_projection_input[32*p+:32])*$signed(wide_weights[32*(4*p+l)+:32]);
            end
            for(genvar p=0;p<4;p=p+1) begin: quarters
                always @(posedge clk)
                    quarter[p]<=(66'(term[4*p])+66'(term[4*p+1]))+(66'(term[4*p+2])+66'(term[4*p+3]));
            end
            always @(posedge clk)
                partial<=(68'(quarter[0])+68'(quarter[1]))+(68'(quarter[2])+68'(quarter[3]));
            assign projection_partial[l]={{4{partial[67]}},partial};
        end else if (PROJECTION_K4 != 0) begin: reduce_projection
            wire signed [63:0] p1 = $signed(projection_input[63:32]) * $signed(wide_weights[(4+l)*32+:32]);
            wire signed [63:0] p2 = $signed(projection_input[95:64]) * $signed(wide_weights[(8+l)*32+:32]);
            wire signed [63:0] p3 = $signed(projection_input[127:96]) * $signed(wide_weights[(12+l)*32+:32]);
            reg signed [65:0] partial;
            always @(posedge clk) if (state==PMAC)
                partial <= ($signed({{2{product[l][63]}},product[l]}) + $signed({{2{p1[63]}},p1})) +
                           ($signed({{2{p2[63]}},p2}) + $signed({{2{p3[63]}},p3}));
            assign projection_partial[l] = {{6{partial[65]}},partial};
        end else begin: scalar_term
            assign projection_partial[l] = sx64(product[l]);
        end
    end endgenerate
    wire signed [71:0] product_sum=sx64(product[0])+sx64(product[1])+sx64(product[2])+sx64(product[3]);
    wire signed [71:0] score_partial;
    genvar attention_lane;
    generate if(ATTENTION_K16!=0) begin: wide_attention_math
        reg signed [63:0] products[0:ATTENTION_LANES-1];
        reg signed [71:0] value_acc[0:ATTENTION_LANES-1];
        reg signed [65:0] score_quarters[0:ATTENTION_LANES/4-1];
        for(attention_lane=0;attention_lane<ATTENTION_LANES;attention_lane=attention_lane+1) begin: lanes
            wire signed [31:0] a=state==SMAC ? $signed(wide_q[32*attention_lane+:32]) : $signed(sd);
            wire signed [31:0] b=state==SMAC ? $signed(wide_k[32*attention_lane+:32]) :
                $signed(wide_v[32*attention_lane+:32]);
            wire signed [71:0] rounded=rne(value_acc[attention_lane],6'd24);
            assign context_words[32*attention_lane+:32]=clip32(rounded);
            assign context_overflows[attention_lane]=overflow32(rounded);
            always @(posedge clk) begin
                if(state==SMAC || state==VMAC) products[attention_lane]<=a*b;
                if(state==VPRIME || state==VSAVE) value_acc[attention_lane]<=0;
                else if((state==VMAC && k!=0) || state==VFLUSH)
                    value_acc[attention_lane]<=value_acc[attention_lane]+sx64(products[attention_lane]);
            end
            if(attention_lane<ATTENTION_LANES/4) begin: score_reduce
                localparam FIRST=attention_lane*4;
                always @(posedge clk)
                    if(PIPELINED_SCORE || (state==SMAC && k!=0) || state==SFLUSH)
                        score_quarters[attention_lane]<=
                            (66'(products[FIRST])+66'(products[FIRST+1]))+
                            (66'(products[FIRST+2])+66'(products[FIRST+3]));
            end
        end
        if(PIPELINED_SCORE) begin: score_pipeline
            reg signed [67:0] half_sum[0:1];
            reg signed [68:0] beat,first_beat;
            reg signed [69:0] total;
            for(genvar s=0;s<2;s=s+1) begin: half_reduce
                always @(posedge clk)
                    half_sum[s]<=(68'(score_quarters[4*s])+68'(score_quarters[4*s+1]))+
                        (68'(score_quarters[4*s+2])+68'(score_quarters[4*s+3]));
            end
            always @(posedge clk) begin
                beat<=69'(half_sum[0])+69'(half_sum[1]);
                if(score_pipe[4] && !score_odd[4]) first_beat<=beat;
                total<=70'(first_beat)+70'(beat);
            end
            assign pipelined_score={{2{total[69]}},total};
            assign score_partial=0;
        end else begin: score_serial
            assign score_partial=(72'(score_quarters[0])+72'(score_quarters[1]))+
                (72'(score_quarters[2])+72'(score_quarters[3]));
            assign pipelined_score=0;
        end
    end else begin: narrow_attention_math
        assign context_words=0;
        assign score_partial=product_sum;
        assign pipelined_score=0;
        assign context_overflows=0;
    end endgenerate
    wire signed [39:0] input_sum={{8{xd[31]}},xd[31:0]}+{{8{xd[63]}},xd[63:32]}+
        {{8{xd[95]}},xd[95:64]}+{{8{xd[127]}},xd[127:96]};
    if(PIPELINED_SCORE) begin: norm_reduction
        always @(posedge clk) begin
            if(state==SUMMAC) sum_partial<=input_sum;
            if(state==VARMAC || state==VARFLUSH) begin
                variance_pair[0]<=sx64(norm_product[0])+sx64(norm_product[1]);
                variance_pair[1]<=sx64(norm_product[2])+sx64(norm_product[3]);
                variance_partial<=variance_pair[0]+variance_pair[1];
            end
        end
    end
    wire math_clear=stopping || state==IDLE;
    wire div_busy,div_done,sqrt_busy,sqrt_done;
    wire [63:0] quotient;wire [31:0] root;
    wire [71:0] variance_wide=($unsigned(acc[0])>>6)+72'd4295;
    kwt_udiv64 #(.SKIP_LEADING(1)) divide(.clk(clk),.rst_n(rst_n),.clear(math_clear),.start(state==EDIV || state==NDIV),
        .numerator(state==EDIV ? 64'h1000000000000 : 64'h1000000000),
        .denominator(state==EDIV ? exp_sum : root),.busy(div_busy),.done(div_done),.quotient(quotient));
    kwt_isqrt64 sqrt_unit(.clk(clk),.rst_n(rst_n),.clear(math_clear),.start(state==SQSTART),
        .value(variance_wide[63:0]),.busy(sqrt_busy),.done(sqrt_done),.root(root));
    wire [39:0] narrow_result=stream_mode ? result_data : compact_buffer[tail_index[2:1]*40+:40];
    wire signed [63:0] tail_source=(stream_mode || compact_mode) ? {{24{narrow_result[39]}},narrow_result} : {m_rdata,low_word};
    wire signed [71:0] tail_value=rne(sx64(tail_source),{1'b0,config_[20:16]})+
        sx32($signed(xd[tail_index[2:1]*32+:32]));
    reg [5:0] sat_events;
    integer i;
    always @* begin
        for(integer u=0;u<4;u=u+1) begin
            lhs[u]=0;rhs[u]=0;
            case(state)
                PMAC:begin lhs[u]=scalar_input;rhs[u]=$signed(wd[u*32+:32]);end
                SMAC:begin lhs[u]=$signed(qd[u*32+:32]);rhs[u]=$signed(kd[u*32+:32]);end
                VMAC:begin lhs[u]=$signed(sd);rhs[u]=$signed(vd[u*32+:32]);end
                VARMAC,VARFLUSH:begin
                    lhs[u]=PIPELINED_SCORE ? norm_centered[u] : centered[u];
                    rhs[u]=PIPELINED_SCORE ? norm_centered[u] : centered[u];
                end
                ANORM,ANORM_MUL:begin
                    lhs[u]=PIPELINED_SCORE ? norm_centered[u] : centered[u];rhs[u]=$signed(reciprocal);
                end
                AFFINE:begin lhs[u]=$signed(norm_value[u*32+:32]);rhs[u]=$signed(gamma[u*32+:32]);end
                NCALC:if(u==0) begin lhs[u]=$signed(sd);rhs[u]=$signed(reciprocal);end
                default:begin end
            endcase
        end
        xcs=0;xwe=0;xm=15;xa=0;xi=0;qcs=0;qwe=0;qm=15;qa=0;qi=0;
        kcs=0;kwe=0;km=15;ka=0;ki=0;vcs=0;vwe=0;vm=15;va=0;vi=0;
        wcs=0;wwe=0;wm=15;wa=0;wi=0;pcs=0;pwe=0;pm=15;pa=0;pi=0;
        scs=0;swe=0;sa=0;si=0;sat_events=0;
        if(loading && retire && !m_err && !stopping) begin
            case(load_kind)
                0:begin xcs=1;xwe=1;xm=4'b1<<load_index[1:0];xa=load_index[12:2];xi={4{m_rdata}};end
                1:begin pcs=1;pwe=1;pm=4'b1<<load_index[1:0];pa=load_index[8:2];pi={4{m_rdata}};end
                default:begin wcs=1;wwe=1;wm=4'b1<<load_index[1:0];wa=load_index[11:2];wi={4{m_rdata}};end
            endcase
        end
        if(state==PINIT && projection==3) begin pcs=1;pa={3'd0,group_};end
        if(state==PPRIME || (state==PMAC && k<PROJECTION_LAST_K)) begin
            wcs=1;wa={group_,projection_read_k};
            if(projection==3) begin
                qcs=1;qa={row,projection_read_k[5:2]};
                qm=PROJECTION_K4 != 0 ? 4'hf : 4'b1<<projection_read_k[1:0];
            end else begin
                xcs=1;xa={row,projection_read_k[5:2]};
                xm=PROJECTION_K4 != 0 ? 4'hf : 4'b1<<projection_read_k[1:0];
            end
        end
        if(state==PSAVE) begin
            if(projection==3) begin xcs=1;xa={row,group_};end
            else begin
                if(projection==0) begin qcs=1;qwe=1;qa={row,group_};end
                if(projection==1) begin kcs=1;kwe=1;ka={row,group_};end
                if(projection==2) begin vcs=1;vwe=1;va={row,group_};end
                for(integer u=0;u<4;u=u+1) begin
                    qi[u*32+:32]=clip32(projected[u]);ki[u*32+:32]=clip32(projected[u]);vi[u*32+:32]=clip32(projected[u]);
                    if(projected[u]>72'sd2147483647 || projected[u]< -72'sd2147483648) sat_events=sat_events+1'b1;
                end
            end
        end
        // Save the old result and prime the next matrix group on independent
        // SRAM ports. Accumulator reset occurs only after its result is saved.
        if(state==PSAVE && another_group) begin
            if(projection==3) begin pcs=1;pa={3'd0,following_group};end
            else begin
                wcs=1;wa={following_group,6'd0};
                xcs=1;xa={following_row,4'd0};xm=PROJECTION_K4 != 0 ? 4'hf : 4'h1;
            end
        end
        if(state==RSAVE && another_group) begin
            wcs=1;wa={following_group,6'd0};
            qcs=1;qa={following_row,4'd0};qm=PROJECTION_K4 != 0 ? 4'hf : 4'h1;
        end
        if(!PIPELINED_SCORE && state==SSAVE && keyrow!=98) begin
            qcs=1;kcs=1;qa={row,4'd0};ka={7'(keyrow+1'b1),4'd0};
        end
        if(state==VSAVE && group_!=VALUE_LAST_GROUP) begin
            scs=1;sa=0;vcs=1;va={7'd0,following_value_group};
        end
        if(state==RSAVE) begin
            xcs=1;xwe=1;xa={row,group_};
            for(integer u=0;u<4;u=u+1) begin
                xi[u*32+:32]=clip32(sx32(clip32(projected[u]))+sx32($signed(xd[u*32+:32])));
                if(projected[u]>72'sd2147483647 || projected[u]< -72'sd2147483648) sat_events=sat_events+1'b1;
                if(overflow32(sx32(clip32(projected[u]))+sx32($signed(xd[u*32+:32])))) sat_events=sat_events+1'b1;
            end
        end
        if(score_fetch) begin
            qcs=1;kcs=1;qa={row,score_issue[0],3'd0};ka={score_issue[7:1],score_issue[0],3'd0};
        end
        if(!PIPELINED_SCORE && (state==SPRIME || (state==SMAC && k<SCORE_LAST_K))) begin
            qcs=1;kcs=1;qa={row,score_read_k};ka={keyrow,score_read_k};
        end
        if(state==SSAVE || score_retire) begin
            scs=1;swe=1;sa=keyrow;si=clip32(rne(PIPELINED_SCORE ? pipelined_score : acc[0],6'd19));
            if(overflow32(rne(PIPELINED_SCORE ? pipelined_score : acc[0],6'd19))) sat_events=sat_events+1'b1;
        end
        if(!PIPELINED_SCORE && (state==EREAD || state==NREAD)) begin scs=1;sa=k;end
        if(exp_retire) begin scs=1;swe=1;sa=k;si=exponential;end
        if(prob_retire) begin
            scs=1;swe=1;sa=k;
            si=PIPELINED_SCORE ? soft_prob_product[55:24] : product[0][55:24];
        end
        if(state==VPRIME || (state==VMAC && k<98)) begin
            scs=1;sa=read_k;vcs=1;va={read_k,group_};
        end
        if(state==VSAVE) begin
            qcs=1;qwe=1;qa={row,group_};
            if(ATTENTION_K16!=0) begin
                qi=context_words[127:0];
                for(integer u=0;u<ATTENTION_LANES;u=u+1)
                    sat_events=sat_events+{5'd0,context_overflows[u]};
            end else
                for(integer u=0;u<4;u=u+1) begin
                    qi[u*32+:32]=clip32(rne(acc[u],6'd24));
                    if(overflow32(rne(acc[u],6'd24))) sat_events=sat_events+1'b1;
                end
        end
        if(state==SUMPRIME || (state==SUMMAC && group_<15) ||
           state==VARPRIME || (state==VARMAC && group_<15)) begin xcs=1;xa={row,read_group};end
        if(state==APRIME) begin xcs=1;xa={row,group_};pcs=1;pa=(norm_second ? 7'd48 : 7'd16)+{3'd0,group_};end
        if(state==ANORM) begin pcs=1;pa=(norm_second ? 7'd64 : 7'd32)+{3'd0,group_};end
        if(state==(PIPELINED_SCORE ? AFFINE_WRITE : AFFINE)) begin
            xcs=1;xwe=1;xa={row,group_};
            for(integer u=0;u<4;u=u+1) begin
                xi[u*32+:32]=clip32(affine_value[u]);
                if(affine_value[u]>72'sd2147483647 || affine_value[u]< -72'sd2147483648) sat_events=sat_events+1'b1;
            end
        end
        if(state==DREAD) begin xcs=1;xa=dump_group;end
        if(dumping && dump_prefetch==0 && dump_group<1583) begin xcs=1;xa=dump_group+1'b1;end
        if(state==TGROUP) begin xcs=1;xa=tail_index[13:3];end
        if(state==TSTORE) begin xcs=1;xwe=1;xa=tail_index[13:3];xi=output_buffer;end
        if((((tail_loading && !compact_mode && retire && !m_err && tail_index[0]) || state==TUNPACK || result_fire) && overflow32(tail_value))) sat_events=sat_events+1'b1;
        if(state==VARMAC) for(integer u=0;u<4;u=u+1)
            if(overflow32(sx32($signed(xd[u*32+:32]))-{{32{mean[39]}},mean})) sat_events=sat_events+1'b1;
        if((state==DCAP || (dumping && dump_prefetch==1)) && !norm_second) for(integer u=0;u<4;u=u+1)
            if(rne(sx32($signed(xd[u*32+:32])),{1'b0,config_[12:8]})>32767 ||
               rne(sx32($signed(xd[u*32+:32])),{1'b0,config_[12:8]})< -32768) sat_events=sat_events+1'b1;
        if(stopping) begin xcs=0;qcs=0;kcs=0;vcs=0;wcs=0;pcs=0;scs=0;sat_events=0;end
    end
    wire [7:0] read_events=(xcs&&!xwe ? (x_wide ? 8'd16 : {4'd0,pop4(xm)}) : 8'd0)+(qcs&&!qwe ? (q_wide ? 8'(ATTENTION_LANES) : {4'd0,pop4(qm)}) : 8'd0)+
        (kcs&&!kwe ? (k_wide ? 8'(ATTENTION_LANES) : {4'd0,pop4(km)}) : 8'd0)+(vcs&&!vwe ? (v_wide ? 8'(ATTENTION_LANES) : {4'd0,pop4(vm)}) : 8'd0)+
        (wcs&&!wwe ? (PROJECTION_K4 != 0 ? 8'(4*PROJECTION_K) : {4'd0,pop4(wm)}) : 8'd0)+
        (pcs&&!pwe ? {4'd0,pop4(pm)} : 8'd0)+(scs&&!swe ? 8'd1 : 8'd0);
    wire [7:0] write_events=(xcs&&xwe ? {4'd0,pop4(xm)} : 8'd0)+(qcs&&qwe ? (q_wide ? 8'(ATTENTION_LANES) : {4'd0,pop4(qm)}) : 8'd0)+
        (kcs&&kwe ? {4'd0,pop4(km)} : 8'd0)+(vcs&&vwe ? {4'd0,pop4(vm)} : 8'd0)+
        (wcs&&wwe ? {4'd0,pop4(wm)} : 8'd0)+(pcs&&pwe ? {4'd0,pop4(pm)} : 8'd0)+(scs&&swe ? 8'd1 : 8'd0);

    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            state<=IDLE;xbase<=0;pbase<=0;fxbase<=0;fybase<=0;ybase<=0;config_<=0;operation<=0;
            done<=0;error<=0;aborted<=0;config_error<=0;abort_pending<=0;resident_valid<=0;z_valid<=0;norm_second<=0;
            load_kind<=0;load_index<=0;tail_index<=0;projection<=0;dump_group<=0;dump_prefetch<=0;
            row<=0;keyrow<=0;k<=0;group_<=0;row_max<=0;sum<=0;mean<=0;exp_sum<=0;reciprocal<=0;low_word<=0;norm_flush<=0;
            output_buffer<=0;norm_value<=0;gamma<=0;compact_word<=0;
            cycles<=0;mac_cycles<=0;read_commands<=0;write_commands<=0;sram_reads<=0;sram_writes<=0;saturations<=0;
            issue_index<=0;pending_count<=0;offer_held<=0;dma_error_pending<=0;
            score_issue<=0;score_pipe<=0;score_odd<=0;
            soft_issue<=0;soft_pipe<=0;soft_delta<=0;soft_prob_product<=0;
            for(i=0;i<10;i=i+1) phase_cycles[i]<=0;
            dma_request_wait<=0;dma_response_wait<=0;dma_retire_refill<=0;
            rsp_valid<=0;rsp_rdata<=0;rsp_err<=0;
            for(i=0;i<4;i=i+1) acc[i]<=0;
        end else begin
            if(rsp_valid && rsp_ready) rsp_valid<=0;
            if(busy) begin
                cycles<=cycles+1'b1;sram_reads<=sram_reads+{23'd0,read_events,1'b0};
                sram_writes<=sram_writes+{23'd0,write_events,1'b0};saturations<=saturations+{26'd0,sat_events};
                if(state==PMAC || state==SMAC || state==VMAC || state==VARMAC || state==ANORM || state==AFFINE || state==NCALC)
                    mac_cycles<=mac_cycles+1'b1;
            end
            pending_count<=pending_next[1:0];
            offer_held<=m_valid && !m_ready;
            if(issue || input_fire) issue_index<=issue_index+1'b1;
            if(PIPELINED_SCORE) begin
                if(state==SINIT) begin score_issue<=0;score_pipe<=0;score_odd<=0;end
                else begin
                    score_pipe<={score_pipe[4:0],score_fetch};
                    score_odd<={score_odd[4:0],score_issue[0]};
                    if(score_fetch) score_issue<=score_issue+1'b1;
                end
                if(state==EREAD || state==ECALC || state==NREAD || state==NCALC) begin
                    soft_pipe<={soft_pipe[4:0],soft_fetch};
                    if(soft_fetch) soft_issue<=soft_issue+1'b1;
                    if(soft_pipe[0] && state==ECALC) soft_delta<=delta;
                    if(soft_pipe[0] && state==NCALC) soft_prob_product<=product[0];
                end else begin soft_pipe<=0;soft_issue<=0;end
            end
            // norm_value is dead during output DMA, so reuse it as the next
            // group's write buffer rather than adding SRAM or arithmetic.
            if(dumping && !stopping) begin
                if(dump_prefetch==0 && dump_group<1583) dump_prefetch<=1;
                else if(dump_prefetch==1) begin
                    dump_prefetch<=2;
                    norm_value<=dump_value;
                end
            end
            if(busy) begin
                if(loading) phase_cycles[7]<=phase_cycles[7]+1'b1;
                else if(state>=TGROUP && state<=TSTREAM) phase_cycles[8]<=phase_cycles[8]+1'b1;
                else if(state>=DREAD && state<=WWAIT) phase_cycles[9]<=phase_cycles[9]+1'b1;
                else if((state>=PINIT && state<=RSAVE) || state==PFLUSH || state==PFLUSH2 || state==PFLUSH3) begin
                    if(projection==3) phase_cycles[4]<=phase_cycles[4]+1'b1;
                    else phase_cycles[0]<=phase_cycles[0]+1'b1;
                end else if((state>=SINIT && state<=SSAVE) || state==SFLUSH || state==SDRAIN)
                    phase_cycles[1]<=phase_cycles[1]+1'b1;
                else if(state>=EREAD && state<=NCALC) phase_cycles[2]<=phase_cycles[2]+1'b1;
                else if((state>=VINIT && state<=VSAVE) || state==VFLUSH) phase_cycles[3]<=phase_cycles[3]+1'b1;
                else if(norm_second) phase_cycles[6]<=phase_cycles[6]+1'b1;
                else phase_cycles[5]<=phase_cycles[5]+1'b1;
                if(m_valid && !m_ready) dma_request_wait<=dma_request_wait+1'b1;
                if(pending_count!=0 && !m_rsp_valid) dma_response_wait<=dma_response_wait+1'b1;
                if(issue && retire) dma_retire_refill<=dma_retire_refill+1'b1;
            end
            if(issue) begin
                if(m_read) read_commands<=read_commands+1'b1;else write_commands<=write_commands+1'b1;
            end
            if(stopping || (retire && m_err)) begin
                if(abort_now || abort_pending) abort_pending<=1;
                if((retire && m_err) || (stream_mode && link_abort_in)) dma_error_pending<=1;
                resident_valid<=0;z_valid<=0;done<=0;
                if(pending_next==0 && !(m_valid && !m_ready)) begin
                    state<=IDLE;aborted<=abort_now || abort_pending;
                    error<=dma_error_pending || (retire && m_err) || (stream_mode && link_abort_in);
                    abort_pending<=0;dma_error_pending<=0;
                end
            end else case(state)
                LREQ,LWAIT:if(retire) begin
                    if(load_index==load_length-1'b1) begin
                        load_index<=0;issue_index<=0;
                        if(load_kind==0) begin load_kind<=1;state<=LREQ;end
                        else if(load_kind==1) begin load_kind<=2;projection<=0;state<=LREQ;end
                        else begin row<=0;group_<=0;k<=0;state<=PINIT;end
                    end else load_index<=load_index+1'b1;
                end
                PINIT:state<=PPRIME;
                PPRIME:begin
                    k<=0;state<=PMAC;
                    for(i=0;i<4;i=i+1) acc[i]<=projection==3 ? sx32($signed(pd[i*32+:32]))<<<16 : 72'sd0;
                end
                PMAC:begin
                    if(PROJECTION_K4 == 0 || (WIDE_PROJECTION ? k>=48 : k!=0))
                        for(i=0;i<4;i=i+1) acc[i]<=acc[i]+projection_partial[i];
                    if(k==PROJECTION_LAST_K) state<=PROJECTION_K4 != 0 ? PFLUSH : PSAVE;
                    else k<=k+7'(PROJECTION_K);
                end
                PFLUSH:begin
                    for(i=0;i<4;i=i+1) acc[i]<=acc[i]+projection_partial[i];
                    state<=WIDE_PROJECTION ? PFLUSH2 : PSAVE;
                end
                PFLUSH2,PFLUSH3:begin
                    for(i=0;i<4;i=i+1) acc[i]<=acc[i]+projection_partial[i];
                    state<=state==PFLUSH2 ? PFLUSH3 : PSAVE;
                end
                PSAVE:begin
                    if(projection==3) state<=RSAVE;
                    else if(another_group) begin
                        row<=following_row;group_<=following_group;k<=0;state<=PMAC;
                        for(i=0;i<4;i=i+1) acc[i]<=0;
                    end
                    else if(projection!=2) begin projection<=projection+1'b1;load_index<=0;issue_index<=0;state<=LREQ;end
                    else begin row<=0;keyrow<=0;row_max<=32'sh80000000;state<=SINIT;end
                end
                RSAVE:begin
                    if(another_group) begin
                        row<=following_row;group_<=following_group;k<=0;state<=PMAC;
                        for(i=0;i<4;i=i+1) acc[i]<=sx32($signed(pd[i*32+:32]))<<<16;
                    end
                    else begin row<=0;norm_second<=0;state<=SUMINIT;end
                end
                SINIT:begin acc[0]<=0;k<=0;state<=SPRIME;end
                SPRIME:state<=SMAC;
                SMAC:begin
                    if(PIPELINED_SCORE) begin
                        if(score_retire) begin
                            if($signed(si)>row_max) row_max<=$signed(si);
                            if(keyrow==98) begin k<=0;exp_sum<=0;state<=EREAD;end
                            else keyrow<=keyrow+1'b1;
                        end
                    end else begin
                        if(ATTENTION_K16==0 || k>=8) acc[0]<=acc[0]+score_partial;
                        if(k==SCORE_LAST_K) state<=ATTENTION_K16!=0 ? SFLUSH : SSAVE;
                        else k<=k+(ATTENTION_K16!=0 ? 7'd4 : 7'd1);
                    end
                end
                SFLUSH:begin acc[0]<=acc[0]+score_partial;state<=SDRAIN;end
                SDRAIN:begin acc[0]<=acc[0]+score_partial;state<=SSAVE;end
                SSAVE:begin
                    if($signed(si)>row_max) row_max<=$signed(si);
                    if(keyrow==98) begin k<=0;exp_sum<=0;state<=EREAD;end
                    else begin keyrow<=keyrow+1'b1;k<=0;acc[0]<=0;state<=SMAC;end
                end
                EREAD:state<=ECALC;
                ECALC:if(exp_retire) begin
                    exp_sum<=exp_sum+exponential;
                    if(k==98) state<=EDIV;
                    else begin k<=k+1'b1;if(!PIPELINED_SCORE) state<=EREAD;end
                end
                EDIV:state<=EDWAIT;
                EDWAIT:if(div_done) begin
                    if(quotient[63:32]!=0) begin error<=1;state<=IDLE;end
                    else begin reciprocal<=quotient[31:0];k<=0;state<=NREAD;end
                end
                NREAD:state<=NCALC;
                NCALC:if(prob_retire) begin
                    if(k==98) begin group_<=0;state<=VINIT;end
                    else begin k<=k+1'b1;if(!PIPELINED_SCORE) state<=NREAD;end
                end
                VINIT:begin for(i=0;i<4;i=i+1) acc[i]<=0;k<=0;state<=VPRIME;end
                VPRIME:state<=VMAC;
                VMAC:begin
                    if(ATTENTION_K16==0)
                        for(i=0;i<4;i=i+1) acc[i]<=acc[i]+sx64(product[i]);
                    if(k==98) state<=ATTENTION_K16!=0 ? VFLUSH : VSAVE;
                    else k<=k+1'b1;
                end
                VFLUSH:state<=VSAVE;
                VSAVE:begin
                    if(group_!=VALUE_LAST_GROUP) begin
                        group_<=following_value_group;k<=0;state<=VMAC;
                        for(i=0;i<4;i=i+1) acc[i]<=0;
                    end
                    else if(row!=98) begin row<=row+1'b1;keyrow<=0;row_max<=32'sh80000000;state<=SINIT;end
                    else begin projection<=3;load_index<=0;load_kind<=2;issue_index<=0;state<=LREQ;end
                end
                SUMINIT:begin group_<=0;sum<=0;state<=SUMPRIME;end
                SUMPRIME:state<=SUMMAC;
                SUMMAC:begin
                    if(!PIPELINED_SCORE || group_!=0) sum<=sum+(PIPELINED_SCORE ? sum_partial : input_sum);
                    if(group_==15) state<=PIPELINED_SCORE ? SUMFLUSH : MEAN;
                    else group_<=group_+1'b1;
                end
                SUMFLUSH:begin sum<=sum+sum_partial;state<=MEAN;end
                MEAN:begin mean<=sum>>>6;acc[0]<=0;group_<=0;state<=VARPRIME;end
                VARPRIME:state<=VARMAC;
                VARMAC:begin
                    if(!PIPELINED_SCORE || group_>=4)
                        acc[0]<=acc[0]+(PIPELINED_SCORE ? variance_partial : product_sum);
                    if(group_==15) begin state<=PIPELINED_SCORE ? VARFLUSH : SQSTART;norm_flush<=0;end
                    else group_<=group_+1'b1;
                end
                VARFLUSH:begin
                    acc[0]<=acc[0]+variance_partial;
                    norm_flush<=norm_flush+1'b1;
                    if(norm_flush==3) state<=SQSTART;
                end
                SQSTART:if(variance_wide[71:64]!=0) begin error<=1;state<=IDLE;end else state<=SQWAIT;
                SQWAIT:if(sqrt_done) state<=NDIV;
                NDIV:state<=NDWAIT;
                NDWAIT:if(div_done) begin
                    if(quotient[63:32]!=0) begin error<=1;state<=IDLE;end
                    else begin reciprocal<=quotient[31:0];group_<=0;state<=APRIME;end
                end
                APRIME:state<=ANORM;
                ANORM:begin
                    gamma<=pd;
                    if(PIPELINED_SCORE) state<=ANORM_MUL;
                    else begin
                        for(i=0;i<4;i=i+1) norm_value[i*32+:32]<=32'(product[i]>>>20);
                        state<=AFFINE;
                    end
                end
                ANORM_MUL:begin
                    for(i=0;i<4;i=i+1) norm_value[i*32+:32]<=32'(product[i]>>>20);
                    state<=AFFINE;
                end
                AFFINE,AFFINE_WRITE:if(PIPELINED_SCORE && state==AFFINE) state<=AFFINE_ROUND;
                else begin
                    if(group_!=15) begin group_<=group_+1'b1;state<=APRIME;end
                    else if(row!=98) begin row<=row+1'b1;state<=SUMINIT;end
                    else if(norm_second && config_[1]) begin state<=IDLE;resident_valid<=1;done<=1;end
                    else begin dump_group<=0;dump_prefetch<=0;state<=DREAD;end
                end
                AFFINE_ROUND:state<=AFFINE_WRITE;
                DREAD:state<=DCAP;
                DCAP:begin
                    output_buffer<=dump_value;
                    dump_prefetch<=0;issue_index<=0;load_index<=0;state<=WREQ;
                end
                WREQ,WWAIT:begin
                    if(dump_fire && (norm_second ? issue_index[1:0]==3 : issue_index[0]) && dump_group<1583) begin
                        dump_group<=dump_group+1'b1;dump_prefetch<=0;
                        // For packed pairs the next group arrives on this very
                        // edge; bypass the prefetch register to sustain 1 word/clk.
                        output_buffer<=dump_prefetch==1 ? dump_value : norm_value;
                    end
                    if(retire || input_fire) begin
                        if(load_index==burst_length-1'b1) begin
                            state<=IDLE;done<=1;if(norm_second) resident_valid<=1;else z_valid<=1;
                        end else load_index<=load_index+1'b1;
                    end
                end
                TGROUP:begin issue_index<=0;compact_word<=0;state<=stream_mode ? TSTREAM : TREQ;end
                TREQ,TWAIT:if(retire) begin
                    if(compact_mode) begin
                        compact_buffer[compact_word*32+:32]<=m_rdata;
                        compact_word<=compact_word+1'b1;
                        if(compact_word==4) state<=TUNPACK;
                    end else begin
                    if(!tail_index[0]) low_word<=m_rdata;
                    else output_buffer[tail_index[2:1]*32+:32]<=clip32(tail_value);
                    if(tail_index[2:0]==7) state<=TSTORE;
                    else tail_index<=tail_index+1'b1;
                    end
                end
                TUNPACK,TSTREAM:if(state==TUNPACK || result_fire) begin
                    output_buffer[tail_index[2:1]*32+:32]<=clip32(tail_value);
                    if(tail_index[2:1]==3) begin tail_index<=tail_index+1'b1;state<=TSTORE;end
                    else tail_index<=tail_index+14'd2;
                end
                TSTORE:begin
                    if(tail_index==12671) begin row<=0;norm_second<=1;state<=SUMINIT;end
                    else begin tail_index<=tail_index+1'b1;state<=TGROUP;end
                end
                default:begin end
            endcase
            if(take) begin
                rsp_valid<=1;rsp_err<=0;rsp_rdata<=0;
                if(cmd_addr[1:0]!=0 || (!cmd_read && cmd_wmask!=15)) begin rsp_err<=1;config_error<=1;end
                else if(cmd_read) case(cmd_addr)
                    20'h04:rsp_rdata<={25'd0,z_valid,resident_valid,config_error,aborted,error,done,busy};
                    20'h0c:rsp_rdata<=32'h454e4331;
                    20'h20:rsp_rdata<=xbase;20'h24:rsp_rdata<=pbase;20'h28:rsp_rdata<=fxbase;
                    20'h2c:rsp_rdata<=fybase;20'h30:rsp_rdata<=ybase;20'h34:rsp_rdata<=config_;20'h38:rsp_rdata<=operation;
                    20'h40:rsp_rdata<=cycles;20'h44:rsp_rdata<=mac_cycles;20'h48:rsp_rdata<=read_commands;
                    20'h4c:rsp_rdata<=write_commands;20'h50:rsp_rdata<=sram_reads;20'h54:rsp_rdata<=sram_writes;
                    20'h58:rsp_rdata<=saturations;20'h5c:rsp_rdata<={24'd0,div_busy,sqrt_busy,state};
                    20'h60:rsp_rdata<=phase_cycles[0];
                    20'h64:rsp_rdata<=phase_cycles[1];
                    20'h68:rsp_rdata<=phase_cycles[2];
                    20'h6c:rsp_rdata<=phase_cycles[3];
                    20'h70:rsp_rdata<=phase_cycles[4];
                    20'h74:rsp_rdata<=phase_cycles[5];
                    20'h78:rsp_rdata<=phase_cycles[6];
                    20'h7c:rsp_rdata<=phase_cycles[7];
                    20'h80:rsp_rdata<=phase_cycles[8];
                    20'h84:rsp_rdata<=phase_cycles[9];
                    20'h88:rsp_rdata<=dma_request_wait;20'h8c:rsp_rdata<=dma_response_wait;
                    20'h90:rsp_rdata<=dma_retire_refill;
                    default:begin rsp_err<=1;config_error<=1;end
                endcase
                else if(cmd_addr==0 && cmd_wdata==2) begin end
                else if(busy) begin rsp_err<=1;config_error<=1;end
                else case(cmd_addr)
                    20'h00:begin
                        if(cmd_wdata==4) begin resident_valid<=0;z_valid<=0;done<=0;error<=0;aborted<=0;config_error<=0;end
                        else if(cmd_wdata!=1 || !addresses_ok || (operation==0 && config_[0] && !resident_valid) || (operation==1 && !z_valid)) begin
                            rsp_err<=1;config_error<=1;
                        end else begin
                            done<=0;error<=0;aborted<=0;config_error<=0;resident_valid<=0;z_valid<=0;norm_second<=operation==1;
                            cycles<=0;mac_cycles<=0;read_commands<=0;write_commands<=0;sram_reads<=0;sram_writes<=0;saturations<=0;
                            issue_index<=0;pending_count<=0;offer_held<=0;dma_error_pending<=0;
                            for(i=0;i<10;i=i+1) phase_cycles[i]<=0;
                            dma_request_wait<=0;dma_response_wait<=0;dma_retire_refill<=0;
                            if(operation==0) begin load_kind<=config_[0] ? 2'd1 : 2'd0;load_index<=0;issue_index<=0;state<=LREQ;end
                            else begin tail_index<=0;state<=TGROUP;end
                        end
                    end
                    20'h20:xbase<=cmd_wdata;20'h24:pbase<=cmd_wdata;20'h28:fxbase<=cmd_wdata;
                    20'h2c:fybase<=cmd_wdata;20'h30:ybase<=cmd_wdata;20'h34:config_<=cmd_wdata;20'h38:operation<=cmd_wdata;
                    default:begin rsp_err<=1;config_error<=1;end
                endcase
            end
        end
    end
endmodule
