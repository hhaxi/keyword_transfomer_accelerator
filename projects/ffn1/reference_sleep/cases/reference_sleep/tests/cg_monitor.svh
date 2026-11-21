// Generated scoreboard: strict task window, no DUT traffic changes.
bit cg_active=0; longint cg_root_edges=0; longint cg_last_root_fs=0;
longint cg_seen[0:0]; longint cg_expected[0:0];
task automatic cg_begin; begin cg_root_edges=0;
for(integer i=0;i<1;i++)begin cg_seen[i]=0;cg_expected[i]=0;end
cg_active=1; end endtask
always @(posedge clk)begin
cg_last_root_fs=measurement_clock.now_fs();
if(cg_active)begin cg_root_edges++;
#0.000001;
end end
task automatic cg_end;begin #0.000001; cg_active=0;
$display("CG_WINDOW task=%0d root_edges=%0d gates=0",taskid,cg_root_edges);
end endtask
