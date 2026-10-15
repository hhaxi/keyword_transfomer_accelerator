// Attention/PostNorm companion to the unchanged full-FFN DMA engine.
// Command 0: Q/K/V -> row Softmax -> PV -> O -> residual -> LN1 -> packed FFN input.
// Command 1: FFN result -> residual -> LN2 -> resident next-layer input / final DMA.
// E203 supplies commands/addresses only; all encoder arithmetic is hardware.
module kwt_encoder(
    input wire clk,rst_n,
    input wire cmd_valid,output wire cmd_ready,input wire [19:0] cmd_addr,
    input wire cmd_read,input wire [31:0] cmd_wdata,input wire [3:0] cmd_wmask,
    output reg rsp_valid,input wire rsp_ready,output reg [31:0] rsp_rdata,output reg rsp_err,
    output wire m_valid,input wire m_ready,output wire [31:0] m_addr,m_wdata,
    output wire m_read,output wire [3:0] m_mask,input wire m_rsp_valid,
    output wire m_rsp_ready,input wire [31:0] m_rdata,input wire m_err
);
    localparam IDLE=0,LREQ=1,LWAIT=2,PINIT=3,PPRIME=4,PMAC=5,PSAVE=6,RSAVE=7,
        SINIT=8,SPRIME=9,SMAC=10,SSAVE=11,EREAD=12,ECALC=13,EDIV=14,EDWAIT=15,
        NREAD=16,NCALC=17,VINIT=18,VPRIME=19,VMAC=20,VSAVE=21,
        SUMINIT=22,SUMPRIME=23,SUMMAC=24,MEAN=25,VARPRIME=26,VARMAC=27,
        SQSTART=28,SQWAIT=29,NDIV=30,NDWAIT=31,APRIME=32,ANORM=33,AFFINE=34,
        DREAD=35,DCAP=36,WREQ=37,WWAIT=38,TGROUP=39,TREQ=40,TWAIT=41,TSTORE=42;
    reg [5:0] state;
    reg [31:0] xbase,pbase,fxbase,fybase,ybase,config_,operation;
    reg done,error,aborted,config_error,abort_pending,resident_valid,z_valid,norm_second;
    reg [1:0] load_kind,projection;
    reg [13:0] load_index,tail_index;
    reg [10:0] dump_group;
    reg [1:0] dump_lane;
    reg [6:0] row,keyrow,k;
    reg [3:0] group_;
    reg signed [71:0] acc[0:3];
    reg signed [31:0] row_max;
    reg signed [39:0] sum,mean;
    reg [31:0] exp_sum,reciprocal,low_word;
    reg [127:0] output_buffer,norm_value,gamma;
    reg [31:0] cycles,mac_cycles,read_commands,write_commands,sram_reads,sram_writes,saturations;
    wire busy=state!=IDLE;
    wire take=cmd_valid && cmd_ready;
    wire wr=take && !cmd_read && cmd_wmask==15 && cmd_addr[1:0]==0;
    wire abort_now=wr && cmd_addr==0 && cmd_wdata==2;
    wire stopping=abort_pending || abort_now;
    assign cmd_ready=!rsp_valid || rsp_ready;
    assign m_valid=state==LREQ || state==WREQ || state==TREQ;
    assign m_read=state!=WREQ && state!=WWAIT;
    assign m_mask=4'hf;
    assign m_rsp_ready=1'b1;
    wire [13:0] load_length=load_kind==0 ? 14'd6336 : load_kind==1 ? 14'd320 : 14'd4096;
    wire [31:0] load_base=load_kind==0 ? xbase : load_kind==1 ? pbase+32'd65536 : pbase+{16'b0,projection,14'b0};
    assign m_addr=(state==TREQ || state==TWAIT) ? fybase+{16'd0,tail_index,2'b0} :
        (state==WREQ || state==WWAIT) ?
            (norm_second ? ybase+{17'd0,dump_group,4'b0} : fxbase+{18'd0,dump_group,3'b0})+{28'd0,dump_lane,2'b0} :
            load_base+{16'd0,load_index,2'b0};
    assign m_wdata=output_buffer[dump_lane*32+:32];

    function automatic signed [71:0] sx32(input signed [31:0] v);
        sx32={{40{v[31]}},v};
    endfunction
    function automatic signed [71:0] sx64(input signed [63:0] v);
        sx64={{8{v[63]}},v};
    endfunction
    function automatic signed [71:0] rne(input signed [71:0] v,input [5:0] shift_);
        reg [71:0] mag,q,rem_,half_;
        begin
            if(shift_==0) rne=v;
            else begin
                mag=v[71] ? $unsigned(-v) : $unsigned(v);
                q=mag>>shift_;rem_=mag&((72'd1<<shift_)-1'b1);half_=72'd1<<(shift_-1'b1);
                if(rem_>half_ || (rem_==half_ && q[0])) q=q+1'b1;
                rne=v[71] ? -$signed(q) : $signed(q);
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
    wire addresses_ok=operation<=1 && (config_&32'hffe0e0fc)==0 &&
        range_ok(xbase,25344) && range_ok(pbase,66816) && range_ok(fxbase,12672) &&
        range_ok(fybase,50688) && range_ok(ybase,25344) &&
        (fxbase+12672<=pbase || pbase+66816<=fxbase) &&
        (fxbase+12672<=fybase || fybase+50688<=fxbase) &&
        (ybase+25344<=pbase || pbase+66816<=ybase) &&
        (ybase+25344<=fybase || fybase+50688<=ybase);

    reg xcs,xwe,qcs,qwe,kcs,kwe,vcs,vwe,wcs,wwe,pcs,pwe,scs,swe;
    reg [3:0] xm,qm,km,vm,wm,pm;
    reg [10:0] xa,qa,ka,va;reg [9:0] wa;reg [6:0] pa,sa;
    reg [127:0] xi,qi,ki,vi,wi,pi;reg [31:0] si;
    wire [127:0] xd,qd,kd,vd,wd,pd;wire [31:0] sd;
    kwt_vecmem32 #(.AW(11)) xm_(clk,xcs,xwe,xm,xa,xi,xd);
    kwt_vecmem32 #(.AW(11)) qm_(clk,qcs,qwe,qm,qa,qi,qd);
    kwt_vecmem32 #(.AW(11)) km_(clk,kcs,kwe,km,ka,ki,kd);
    kwt_vecmem32 #(.AW(11)) vm_(clk,vcs,vwe,vm,va,vi,vd);
    kwt_vecmem32 #(.AW(10)) wm_(clk,wcs,wwe,wm,wa,wi,wd);
    kwt_vecmem32 #(.AW(7)) pm_(clk,pcs,pwe,pm,pa,pi,pd);
    kwt_sram16 #(.AW(7)) score_lo(clk,scs,swe,sa,si[15:0],sd[15:0]);
    kwt_sram16 #(.AW(7)) score_hi(clk,scs,swe,sa,si[31:16],sd[31:16]);
    wire [6:0] next_k=k+1'b1;
    wire [6:0] read_k=(state==PPRIME || state==SPRIME || state==VPRIME) ? 7'd0 : next_k;
    wire [3:0] next_group=group_+1'b1;
    wire [3:0] read_group=(state==SUMPRIME || state==VARPRIME) ? 4'd0 : next_group;
    wire [127:0] projection_input=projection==3 ? qd : xd;
    wire signed [31:0] scalar_input=projection_input[k[1:0]*32+:32];
    wire signed [32:0] delta=$signed({row_max[31],row_max})-$signed({sd[31],sd});
    wire [31:0] exponential;
    wire [32:0] delta_unsigned=delta;
    kwt_exp_negative exp_unit(.delta(delta_unsigned),.result(exponential));

    reg signed [31:0] lhs[0:3],rhs[0:3];
    wire signed [63:0] product[0:3];
    wire signed [31:0] centered[0:3];
    wire signed [71:0] projected[0:3],affine_value[0:3];
    genvar l;
    generate for(l=0;l<4;l=l+1) begin: arithmetic
        assign product[l]=lhs[l]*rhs[l];
        assign centered[l]=clip32(sx32($signed(xd[l*32+:32]))-{{32{mean[39]}},mean});
        assign projected[l]=rne(acc[l],6'd16);
        assign affine_value[l]=rne(sx64(product[l]),6'd16)+sx32($signed(pd[l*32+:32]));
    end endgenerate
    wire signed [71:0] product_sum=sx64(product[0])+sx64(product[1])+sx64(product[2])+sx64(product[3]);
    wire signed [39:0] input_sum={{8{xd[31]}},xd[31:0]}+{{8{xd[63]}},xd[63:32]}+
        {{8{xd[95]}},xd[95:64]}+{{8{xd[127]}},xd[127:96]};
    wire math_clear=stopping || state==IDLE;
    wire div_busy,div_done,sqrt_busy,sqrt_done;
    wire [63:0] quotient;wire [31:0] root;
    wire [71:0] variance_wide=($unsigned(acc[0])>>6)+72'd4295;
    kwt_udiv64 divide(.clk(clk),.rst_n(rst_n),.clear(math_clear),.start(state==EDIV || state==NDIV),
        .numerator(state==EDIV ? 64'h1000000000000 : 64'h1000000000),
        .denominator(state==EDIV ? exp_sum : root),.busy(div_busy),.done(div_done),.quotient(quotient));
    kwt_isqrt64 sqrt_unit(.clk(clk),.rst_n(rst_n),.clear(math_clear),.start(state==SQSTART),
        .value(variance_wide[63:0]),.busy(sqrt_busy),.done(sqrt_done),.root(root));
    wire signed [71:0] tail_value=rne(sx64($signed({m_rdata,low_word})),{1'b0,config_[20:16]})+
        sx32($signed(xd[tail_index[2:1]*32+:32]));
    reg [3:0] sat_events;
    integer i;
    always @* begin
        for(integer u=0;u<4;u=u+1) begin
            lhs[u]=0;rhs[u]=0;
            case(state)
                PMAC:begin lhs[u]=scalar_input;rhs[u]=$signed(wd[u*32+:32]);end
                SMAC:begin lhs[u]=$signed(qd[u*32+:32]);rhs[u]=$signed(kd[u*32+:32]);end
                VMAC:begin lhs[u]=$signed(sd);rhs[u]=$signed(vd[u*32+:32]);end
                VARMAC:begin lhs[u]=centered[u];rhs[u]=centered[u];end
                ANORM:begin lhs[u]=centered[u];rhs[u]=$signed(reciprocal);end
                AFFINE:begin lhs[u]=$signed(norm_value[u*32+:32]);rhs[u]=$signed(gamma[u*32+:32]);end
                NCALC:if(u==0) begin lhs[u]=$signed(sd);rhs[u]=$signed(reciprocal);end
                default:begin end
            endcase
        end
        xcs=0;xwe=0;xm=15;xa=0;xi=0;qcs=0;qwe=0;qm=15;qa=0;qi=0;
        kcs=0;kwe=0;km=15;ka=0;ki=0;vcs=0;vwe=0;vm=15;va=0;vi=0;
        wcs=0;wwe=0;wm=15;wa=0;wi=0;pcs=0;pwe=0;pm=15;pa=0;pi=0;
        scs=0;swe=0;sa=0;si=0;sat_events=0;
        if(state==LWAIT && m_rsp_valid && !m_err && !stopping) begin
            case(load_kind)
                0:begin xcs=1;xwe=1;xm=4'b1<<load_index[1:0];xa=load_index[12:2];xi={4{m_rdata}};end
                1:begin pcs=1;pwe=1;pm=4'b1<<load_index[1:0];pa=load_index[8:2];pi={4{m_rdata}};end
                default:begin wcs=1;wwe=1;wm=4'b1<<load_index[1:0];wa=load_index[11:2];wi={4{m_rdata}};end
            endcase
        end
        if(state==PINIT && projection==3) begin pcs=1;pa={3'd0,group_};end
        if(state==PPRIME || (state==PMAC && k<63)) begin
            wcs=1;wa={group_,read_k[5:0]};
            if(projection==3) begin qcs=1;qa={row,read_k[5:2]};qm=4'b1<<read_k[1:0];end
            else begin xcs=1;xa={row,read_k[5:2]};xm=4'b1<<read_k[1:0];end
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
        if(state==RSAVE) begin
            xcs=1;xwe=1;xa={row,group_};
            for(integer u=0;u<4;u=u+1) begin
                xi[u*32+:32]=clip32(sx32(clip32(projected[u]))+sx32($signed(xd[u*32+:32])));
                if(projected[u]>72'sd2147483647 || projected[u]< -72'sd2147483648) sat_events=sat_events+1'b1;
                if(overflow32(sx32(clip32(projected[u]))+sx32($signed(xd[u*32+:32])))) sat_events=sat_events+1'b1;
            end
        end
        if(state==SPRIME || (state==SMAC && k<15)) begin
            qcs=1;kcs=1;qa={row,read_k[3:0]};ka={keyrow,read_k[3:0]};
        end
        if(state==SSAVE) begin
            scs=1;swe=1;sa=keyrow;si=clip32(rne(acc[0],6'd19));
            if(overflow32(rne(acc[0],6'd19))) sat_events=sat_events+1'b1;
        end
        if(state==EREAD || state==NREAD) begin scs=1;sa=k;end
        if(state==ECALC) begin scs=1;swe=1;sa=k;si=exponential;end
        if(state==NCALC) begin scs=1;swe=1;sa=k;si=32'($unsigned(product[0])>>24);end
        if(state==VPRIME || (state==VMAC && k<98)) begin
            scs=1;sa=read_k;vcs=1;va={read_k,group_};
        end
        if(state==VSAVE) begin
            qcs=1;qwe=1;qa={row,group_};
            for(integer u=0;u<4;u=u+1) begin
                qi[u*32+:32]=clip32(rne(acc[u],6'd24));
                if(overflow32(rne(acc[u],6'd24))) sat_events=sat_events+1'b1;
            end
        end
        if(state==SUMPRIME || (state==SUMMAC && group_<15) ||
           state==VARPRIME || (state==VARMAC && group_<15)) begin xcs=1;xa={row,read_group};end
        if(state==APRIME) begin xcs=1;xa={row,group_};pcs=1;pa=(norm_second ? 7'd48 : 7'd16)+{3'd0,group_};end
        if(state==ANORM) begin pcs=1;pa=(norm_second ? 7'd64 : 7'd32)+{3'd0,group_};end
        if(state==AFFINE) begin
            xcs=1;xwe=1;xa={row,group_};
            for(integer u=0;u<4;u=u+1) begin
                xi[u*32+:32]=clip32(affine_value[u]);
                if(affine_value[u]>72'sd2147483647 || affine_value[u]< -72'sd2147483648) sat_events=sat_events+1'b1;
            end
        end
        if(state==DREAD) begin xcs=1;xa=dump_group;end
        if(state==TGROUP) begin xcs=1;xa=tail_index[13:3];end
        if(state==TSTORE) begin xcs=1;xwe=1;xa=tail_index[13:3];xi=output_buffer;end
        if(state==TWAIT && m_rsp_valid && !m_err && tail_index[0] && overflow32(tail_value)) sat_events=sat_events+1'b1;
        if(state==VARMAC) for(integer u=0;u<4;u=u+1)
            if(overflow32(sx32($signed(xd[u*32+:32]))-{{32{mean[39]}},mean})) sat_events=sat_events+1'b1;
        if(state==DCAP && !norm_second) for(integer u=0;u<4;u=u+1)
            if(rne(sx32($signed(xd[u*32+:32])),{1'b0,config_[12:8]})>32767 ||
               rne(sx32($signed(xd[u*32+:32])),{1'b0,config_[12:8]})< -32768) sat_events=sat_events+1'b1;
        if(stopping) begin xcs=0;qcs=0;kcs=0;vcs=0;wcs=0;pcs=0;scs=0;sat_events=0;end
    end
    wire [7:0] read_events=(xcs&&!xwe ? {4'd0,pop4(xm)} : 8'd0)+(qcs&&!qwe ? {4'd0,pop4(qm)} : 8'd0)+
        (kcs&&!kwe ? {4'd0,pop4(km)} : 8'd0)+(vcs&&!vwe ? {4'd0,pop4(vm)} : 8'd0)+
        (wcs&&!wwe ? {4'd0,pop4(wm)} : 8'd0)+(pcs&&!pwe ? {4'd0,pop4(pm)} : 8'd0)+(scs&&!swe ? 8'd1 : 8'd0);
    wire [7:0] write_events=(xcs&&xwe ? {4'd0,pop4(xm)} : 8'd0)+(qcs&&qwe ? {4'd0,pop4(qm)} : 8'd0)+
        (kcs&&kwe ? {4'd0,pop4(km)} : 8'd0)+(vcs&&vwe ? {4'd0,pop4(vm)} : 8'd0)+
        (wcs&&wwe ? {4'd0,pop4(wm)} : 8'd0)+(pcs&&pwe ? {4'd0,pop4(pm)} : 8'd0)+(scs&&swe ? 8'd1 : 8'd0);

    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            state<=IDLE;xbase<=0;pbase<=0;fxbase<=0;fybase<=0;ybase<=0;config_<=0;operation<=0;
            done<=0;error<=0;aborted<=0;config_error<=0;abort_pending<=0;resident_valid<=0;z_valid<=0;norm_second<=0;
            load_kind<=0;load_index<=0;tail_index<=0;projection<=0;dump_group<=0;dump_lane<=0;
            row<=0;keyrow<=0;k<=0;group_<=0;row_max<=0;sum<=0;mean<=0;exp_sum<=0;reciprocal<=0;low_word<=0;
            output_buffer<=0;norm_value<=0;gamma<=0;
            cycles<=0;mac_cycles<=0;read_commands<=0;write_commands<=0;sram_reads<=0;sram_writes<=0;saturations<=0;
            rsp_valid<=0;rsp_rdata<=0;rsp_err<=0;
            for(i=0;i<4;i=i+1) acc[i]<=0;
        end else begin
            if(rsp_valid && rsp_ready) rsp_valid<=0;
            if(busy) begin
                cycles<=cycles+1'b1;sram_reads<=sram_reads+{23'd0,read_events,1'b0};
                sram_writes<=sram_writes+{23'd0,write_events,1'b0};saturations<=saturations+{28'd0,sat_events};
                if(state==PMAC || state==SMAC || state==VMAC || state==VARMAC || state==ANORM || state==AFFINE || state==NCALC)
                    mac_cycles<=mac_cycles+1'b1;
            end
            if(m_valid && m_ready) begin
                if(m_read) read_commands<=read_commands+1'b1;else write_commands<=write_commands+1'b1;
            end
            if(stopping) begin
                abort_pending<=1;resident_valid<=0;z_valid<=0;done<=0;
                if(state==LREQ && m_ready) state<=LWAIT;
                else if(state==WREQ && m_ready) state<=WWAIT;
                else if(state==TREQ && m_ready) state<=TWAIT;
                else if((state==LWAIT || state==WWAIT || state==TWAIT) && m_rsp_valid) begin
                    state<=IDLE;aborted<=1;abort_pending<=0;
                end else if(state!=LREQ && state!=WREQ && state!=TREQ && state!=LWAIT && state!=WWAIT && state!=TWAIT) begin
                    state<=IDLE;aborted<=1;abort_pending<=0;
                end
            end else if((state==LWAIT || state==WWAIT || state==TWAIT) && m_rsp_valid && m_err) begin
                state<=IDLE;error<=1;resident_valid<=0;z_valid<=0;done<=0;
            end else case(state)
                LREQ:if(m_ready) state<=LWAIT;
                LWAIT:if(m_rsp_valid) begin
                    if(load_index==load_length-1'b1) begin
                        load_index<=0;
                        if(load_kind==0) begin load_kind<=1;state<=LREQ;end
                        else if(load_kind==1) begin load_kind<=2;projection<=0;state<=LREQ;end
                        else begin row<=0;group_<=0;k<=0;state<=PINIT;end
                    end else begin load_index<=load_index+1'b1;state<=LREQ;end
                end
                PINIT:state<=PPRIME;
                PPRIME:begin
                    k<=0;state<=PMAC;
                    for(i=0;i<4;i=i+1) acc[i]<=projection==3 ? sx32($signed(pd[i*32+:32]))<<<16 : 72'sd0;
                end
                PMAC:begin
                    for(i=0;i<4;i=i+1) acc[i]<=acc[i]+sx64(product[i]);
                    if(k==63) state<=PSAVE;else k<=k+1'b1;
                end
                PSAVE:begin
                    if(projection==3) state<=RSAVE;
                    else if(group_!=15) begin group_<=group_+1'b1;state<=PINIT;end
                    else if(row!=98) begin row<=row+1'b1;group_<=0;state<=PINIT;end
                    else if(projection!=2) begin projection<=projection+1'b1;load_index<=0;state<=LREQ;end
                    else begin row<=0;keyrow<=0;row_max<=32'sh80000000;state<=SINIT;end
                end
                RSAVE:begin
                    if(group_!=15) begin group_<=group_+1'b1;state<=PINIT;end
                    else if(row!=98) begin row<=row+1'b1;group_<=0;state<=PINIT;end
                    else begin row<=0;norm_second<=0;state<=SUMINIT;end
                end
                SINIT:begin acc[0]<=0;k<=0;state<=SPRIME;end
                SPRIME:state<=SMAC;
                SMAC:begin acc[0]<=acc[0]+product_sum;if(k==15) state<=SSAVE;else k<=k+1'b1;end
                SSAVE:begin
                    if($signed(si)>row_max) row_max<=$signed(si);
                    if(keyrow==98) begin k<=0;exp_sum<=0;state<=EREAD;end
                    else begin keyrow<=keyrow+1'b1;state<=SINIT;end
                end
                EREAD:state<=ECALC;
                ECALC:begin
                    exp_sum<=exp_sum+exponential;
                    if(k==98) state<=EDIV;else begin k<=k+1'b1;state<=EREAD;end
                end
                EDIV:state<=EDWAIT;
                EDWAIT:if(div_done) begin
                    if(quotient[63:32]!=0) begin error<=1;state<=IDLE;end
                    else begin reciprocal<=quotient[31:0];k<=0;state<=NREAD;end
                end
                NREAD:state<=NCALC;
                NCALC:if(k==98) begin group_<=0;state<=VINIT;end else begin k<=k+1'b1;state<=NREAD;end
                VINIT:begin for(i=0;i<4;i=i+1) acc[i]<=0;k<=0;state<=VPRIME;end
                VPRIME:state<=VMAC;
                VMAC:begin
                    for(i=0;i<4;i=i+1) acc[i]<=acc[i]+sx64(product[i]);
                    if(k==98) state<=VSAVE;else k<=k+1'b1;
                end
                VSAVE:begin
                    if(group_!=15) begin group_<=group_+1'b1;state<=VINIT;end
                    else if(row!=98) begin row<=row+1'b1;keyrow<=0;row_max<=32'sh80000000;state<=SINIT;end
                    else begin projection<=3;load_index<=0;load_kind<=2;state<=LREQ;end
                end
                SUMINIT:begin group_<=0;sum<=0;state<=SUMPRIME;end
                SUMPRIME:state<=SUMMAC;
                SUMMAC:begin sum<=sum+input_sum;if(group_==15) state<=MEAN;else group_<=group_+1'b1;end
                MEAN:begin mean<=sum>>>6;acc[0]<=0;group_<=0;state<=VARPRIME;end
                VARPRIME:state<=VARMAC;
                VARMAC:begin acc[0]<=acc[0]+product_sum;if(group_==15) state<=SQSTART;else group_<=group_+1'b1;end
                SQSTART:if(variance_wide[71:64]!=0) begin error<=1;state<=IDLE;end else state<=SQWAIT;
                SQWAIT:if(sqrt_done) state<=NDIV;
                NDIV:state<=NDWAIT;
                NDWAIT:if(div_done) begin
                    if(quotient[63:32]!=0) begin error<=1;state<=IDLE;end
                    else begin reciprocal<=quotient[31:0];group_<=0;state<=APRIME;end
                end
                APRIME:state<=ANORM;
                ANORM:begin
                    for(i=0;i<4;i=i+1) norm_value[i*32+:32]<=32'(product[i]>>>20);
                    gamma<=pd;state<=AFFINE;
                end
                AFFINE:begin
                    if(group_!=15) begin group_<=group_+1'b1;state<=APRIME;end
                    else if(row!=98) begin row<=row+1'b1;state<=SUMINIT;end
                    else if(norm_second && config_[1]) begin state<=IDLE;resident_valid<=1;done<=1;end
                    else begin dump_group<=0;dump_lane<=0;state<=DREAD;end
                end
                DREAD:state<=DCAP;
                DCAP:begin
                    if(norm_second) output_buffer<=xd;
                    else begin
                        for(i=0;i<4;i=i+1) output_buffer[i*16+:16]<=clip16(rne(sx32($signed(xd[i*32+:32])),{1'b0,config_[12:8]}));
                        output_buffer[127:64]<=0;
                    end
                    dump_lane<=0;state<=WREQ;
                end
                WREQ:if(m_ready) state<=WWAIT;
                WWAIT:if(m_rsp_valid) begin
                    if(dump_lane==(norm_second ? 2'd3 : 2'd1)) begin
                        if(dump_group==1583) begin
                            state<=IDLE;done<=1;if(norm_second) resident_valid<=1;else z_valid<=1;
                        end else begin dump_group<=dump_group+1'b1;state<=DREAD;end
                    end else begin dump_lane<=dump_lane+1'b1;state<=WREQ;end
                end
                TGROUP:state<=TREQ;
                TREQ:if(m_ready) state<=TWAIT;
                TWAIT:if(m_rsp_valid) begin
                    if(!tail_index[0]) low_word<=m_rdata;
                    else output_buffer[tail_index[2:1]*32+:32]<=clip32(tail_value);
                    if(tail_index[2:0]==7) state<=TSTORE;
                    else begin tail_index<=tail_index+1'b1;state<=TREQ;end
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
                            if(operation==0) begin load_kind<=config_[0] ? 2'd1 : 2'd0;load_index<=0;state<=LREQ;end
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
