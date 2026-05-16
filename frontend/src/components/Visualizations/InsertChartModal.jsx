import React, { useState, useMemo } from 'react';
import { createPortal } from 'react-dom';
import {
  BarChart, Bar, LineChart, Line, AreaChart, Area,
  PieChart, Pie, Cell, ScatterChart, Scatter,
  RadarChart, Radar, PolarGrid, PolarAngleAxis,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer, ComposedChart,
} from 'recharts';
import './InsertChartModal.css';

// ── Chart category definitions ────────────────────────────────────
const CATEGORIES = [
  { id: 'column',    icon: '📊', label: 'Column' },
  { id: 'bar',       icon: '📉', label: 'Bar' },
  { id: 'line',      icon: '📈', label: 'Line' },
  { id: 'area',      icon: '🏔️', label: 'Area' },
  { id: 'pie',       icon: '🥧', label: 'Pie' },
  { id: 'scatter',   icon: '✦',  label: 'X Y (Scatter)' },
  { id: 'radar',     icon: '🕸️', label: 'Radar' },
  { id: 'combo',     icon: '🔀', label: 'Combo' },
  { id: 'histogram', icon: '▬',  label: 'Histogram' },
];

const SUBTYPES = {
  column:    [
    { id: 'clustered',     label: 'Clustered Column' },
    { id: 'stacked',       label: 'Stacked Column' },
    { id: 'pct_stacked',   label: '100% Stacked' },
  ],
  bar:       [
    { id: 'clustered',     label: 'Clustered Bar' },
    { id: 'stacked',       label: 'Stacked Bar' },
  ],
  line:      [
    { id: 'line',          label: 'Line' },
    { id: 'smooth',        label: 'Smooth Line' },
    { id: 'stepped',       label: 'Step Line' },
  ],
  area:      [
    { id: 'area',          label: 'Area' },
    { id: 'stacked',       label: 'Stacked Area' },
  ],
  pie:       [
    { id: 'pie',           label: 'Pie' },
    { id: 'donut',         label: 'Donut' },
  ],
  scatter:   [
    { id: 'scatter',       label: 'Scatter' },
    { id: 'bubble',        label: 'Bubble' },
  ],
  radar:     [
    { id: 'radar',         label: 'Radar' },
    { id: 'filled',        label: 'Filled Radar' },
  ],
  combo:     [
    { id: 'bar_line',      label: 'Bar + Line' },
  ],
  histogram: [
    { id: 'histogram',     label: 'Histogram' },
  ],
};

// ── Subtype SVG thumbnails ────────────────────────────────────────
function SubtypeThumb({ catId, subtypeId, active }) {
  const color = active ? '#6366f1' : '#94a3b8';
  const bg    = active ? 'rgba(99,102,241,0.12)' : 'transparent';
  const s = { width: 52, height: 42, display: 'block' };

  const thumbs = {
    column_clustered:   <svg style={s} viewBox="0 0 52 42"><rect x="5"  y="16" width="9" height="24" fill={color}/><rect x="17" y="8"  width="9" height="32" fill={color} opacity=".7"/><rect x="29" y="20" width="9" height="20" fill={color} opacity=".5"/><rect x="41" y="12" width="9" height="28" fill={color} opacity=".6"/></svg>,
    column_stacked:     <svg style={s} viewBox="0 0 52 42"><rect x="8"  y="20" width="12" height="20" fill={color}/><rect x="8"  y="10" width="12" height="10" fill={color} opacity=".55"/><rect x="25" y="14" width="12" height="26" fill={color}/><rect x="25" y="6"  width="12" height="8"  fill={color} opacity=".55"/></svg>,
    column_pct_stacked: <svg style={s} viewBox="0 0 52 42"><rect x="8"  y="20" width="12" height="20" fill={color}/><rect x="8"  y="4"  width="12" height="16" fill={color} opacity=".45"/><rect x="25" y="20" width="12" height="20" fill={color}/><rect x="25" y="4"  width="12" height="16" fill={color} opacity=".45"/></svg>,
    bar_clustered:      <svg style={s} viewBox="0 0 52 42"><rect y="5"  x="5"  height="8"  width="30" fill={color}/><rect y="17" x="5"  height="8"  width="20" fill={color} opacity=".7"/><rect y="29" x="5"  height="8"  width="38" fill={color} opacity=".5"/></svg>,
    bar_stacked:        <svg style={s} viewBox="0 0 52 42"><rect y="5"  x="5"  height="8"  width="20" fill={color}/><rect y="5"  x="25" height="8"  width="15" fill={color} opacity=".5"/><rect y="17" x="5"  height="8"  width="28" fill={color}/><rect y="17" x="33" height="8"  width="10" fill={color} opacity=".5"/></svg>,
    line_line:          <svg style={s} viewBox="0 0 52 42"><polyline points="4,34 16,20 28,26 40,10 52,18" fill="none" stroke={color} strokeWidth="2.5"/></svg>,
    line_smooth:        <svg style={s} viewBox="0 0 52 42"><path d="M4,34 C12,20 20,30 28,18 C36,6 44,22 52,14" fill="none" stroke={color} strokeWidth="2.5"/></svg>,
    line_stepped:       <svg style={s} viewBox="0 0 52 42"><polyline points="4,34 16,34 16,20 28,20 28,28 40,28 40,10 52,10" fill="none" stroke={color} strokeWidth="2.5"/></svg>,
    area_area:          <svg style={s} viewBox="0 0 52 42"><path d="M4,34 C12,20 20,28 28,16 C36,4 44,18 52,14 L52,40 L4,40Z" fill={color} opacity=".35" stroke={color} strokeWidth="1.5"/></svg>,
    area_stacked:       <svg style={s} viewBox="0 0 52 42"><path d="M4,30 L20,22 L36,26 L52,18 L52,40 L4,40Z" fill={color} opacity=".5"/><path d="M4,20 L20,12 L36,16 L52,8 L52,22 L36,26 L20,22 L4,30Z" fill={color} opacity=".3"/></svg>,
    pie_pie:            <svg style={s} viewBox="0 0 52 42"><circle cx="26" cy="21" r="16" fill="none" stroke={color} strokeWidth="32" strokeDasharray="25 75" strokeDashoffset="25"/><circle cx="26" cy="21" r="16" fill="none" stroke={color} opacity=".5" strokeWidth="32" strokeDasharray="35 65" strokeDashoffset="-50"/></svg>,
    pie_donut:          <svg style={s} viewBox="0 0 52 42"><circle cx="26" cy="21" r="15" fill="none" stroke={color} strokeWidth="9"/><circle cx="26" cy="21" r="15" fill="none" stroke={color} opacity=".4" strokeWidth="9" strokeDasharray="20 30" strokeDashoffset="10"/></svg>,
    scatter_scatter:    <svg style={s} viewBox="0 0 52 42">{[[8,32],[16,18],[24,28],[30,10],[38,22],[46,14]].map(([x,y],i)=><circle key={i} cx={x} cy={y} r="3" fill={color} opacity=".8"/>)}</svg>,
    scatter_bubble:     <svg style={s} viewBox="0 0 52 42">{[[10,30,6],[22,16,9],[36,26,5],[44,12,7]].map(([x,y,r],i)=><circle key={i} cx={x} cy={y} r={r} fill={color} opacity=".55"/>)}</svg>,
    radar_radar:        <svg style={s} viewBox="0 0 52 42"><polygon points="26,4 46,30 10,30" fill="none" stroke={color} strokeWidth="1" opacity=".5"/><polygon points="26,10 38,28 14,28" fill={color} opacity=".25" stroke={color} strokeWidth="1.5"/></svg>,
    radar_filled:       <svg style={s} viewBox="0 0 52 42"><polygon points="26,4 46,30 10,30" fill={color} opacity=".3" stroke={color} strokeWidth="1.5"/></svg>,
    combo_bar_line:     <svg style={s} viewBox="0 0 52 42"><rect x="5"  y="18" width="8" height="22" fill={color} opacity=".7"/><rect x="17" y="10" width="8" height="30" fill={color} opacity=".7"/><rect x="29" y="20" width="8" height="20" fill={color} opacity=".7"/><rect x="41" y="14" width="8" height="26" fill={color} opacity=".7"/><polyline points="9,18 21,8 33,14 45,6" fill="none" stroke="#ef4444" strokeWidth="2.5"/></svg>,
    histogram_histogram:<svg style={s} viewBox="0 0 52 42"><rect x="4"  y="26" width="7" height="14" fill={color}/><rect x="13" y="16" width="7" height="24" fill={color} opacity=".8"/><rect x="22" y="8"  width="7" height="32" fill={color} opacity=".9"/><rect x="31" y="14" width="7" height="26" fill={color} opacity=".7"/><rect x="40" y="22" width="7" height="18" fill={color} opacity=".6"/></svg>,
  };
  const key = `${catId}_${subtypeId}`;
  return (
    <div className={`ict-subtype ${active ? 'ict-subtype--active' : ''}`} style={{ background: bg }}>
      {thumbs[key] || <svg style={s} viewBox="0 0 52 42"><rect x="8" y="10" width="36" height="28" rx="4" fill={color} opacity=".3"/></svg>}
    </div>
  );
}

// ── Live chart preview with real data ─────────────────────────────
const PALETTE = ['#6366f1','#8b5cf6','#06b6d4','#10b981','#f59e0b','#ef4444'];

function LivePreview({ catId, subtypeId, data, xKey, yKey, yKey2 }) {
  if (!data || data.length === 0) {
    return <div className="ict-preview-empty">No data available for preview</div>;
  }
  const h = "100%";
  const commonProps = { data, margin: { top: 10, right: 16, left: -10, bottom: 36 } };
  const axis = <>
    <CartesianGrid strokeDasharray="3 3" stroke="rgba(148,163,184,0.2)" vertical={false}/>
    <XAxis dataKey={xKey} tick={{ fontSize: 9 }} angle={-30} textAnchor="end"/>
    <YAxis tick={{ fontSize: 9 }} axisLine={false} tickLine={false}/>
    <Tooltip contentStyle={{ fontSize: 11 }}/>
  </>;

  if (catId === 'column') {
    const stacked = subtypeId !== 'clustered';
    return <ResponsiveContainer width="100%" height={h}><BarChart {...commonProps}>{axis}<Bar dataKey={yKey} stackId={stacked ? 'a' : undefined} fill={PALETTE[0]} radius={[3,3,0,0]}/>{yKey2 && <Bar dataKey={yKey2} stackId={stacked ? 'a' : undefined} fill={PALETTE[1]} radius={[3,3,0,0]}/>}</BarChart></ResponsiveContainer>;
  }
  if (catId === 'bar') {
    return <ResponsiveContainer width="100%" height={h}><BarChart {...commonProps} layout="vertical" margin={{ top:10,right:16,left:10,bottom:10 }}><CartesianGrid strokeDasharray="3 3" stroke="rgba(148,163,184,0.2)" horizontal={false}/><XAxis type="number" tick={{ fontSize:9 }} axisLine={false}/><YAxis type="category" dataKey={xKey} tick={{ fontSize:9 }} width={70}/><Tooltip contentStyle={{ fontSize:11 }}/><Bar dataKey={yKey} fill={PALETTE[0]} radius={[0,4,4,0]}/>{yKey2 && <Bar dataKey={yKey2} fill={PALETTE[1]} radius={[0,4,4,0]}/>}</BarChart></ResponsiveContainer>;
  }
  if (catId === 'line') {
    const t = subtypeId === 'smooth' ? 'monotone' : subtypeId === 'stepped' ? 'step' : 'linear';
    return <ResponsiveContainer width="100%" height={h}><LineChart {...commonProps}>{axis}<Line type={t} dataKey={yKey} stroke={PALETTE[0]} strokeWidth={2} dot={{ r:2 }}/>{yKey2 && <Line type={t} dataKey={yKey2} stroke={PALETTE[1]} strokeWidth={2} dot={{ r:2 }}/>}</LineChart></ResponsiveContainer>;
  }
  if (catId === 'area') {
    return <ResponsiveContainer width="100%" height={h}><AreaChart {...commonProps}>{axis}<Area type="monotone" dataKey={yKey} stroke={PALETTE[0]} fill={PALETTE[0]+'44'} strokeWidth={2}/>{yKey2 && <Area type="monotone" dataKey={yKey2} stroke={PALETTE[1]} fill={PALETTE[1]+'44'} strokeWidth={2}/>}</AreaChart></ResponsiveContainer>;
  }
  if (catId === 'pie') {
    const isDonut = subtypeId === 'donut';
    return <ResponsiveContainer width="100%" height={h}><PieChart><Pie data={data} dataKey={yKey} nameKey={xKey} cx="50%" cy="50%" outerRadius={isDonut?80:90} innerRadius={isDonut?45:0}>{data.map((_,i)=><Cell key={i} fill={PALETTE[i%PALETTE.length]}/>)}</Pie><Tooltip contentStyle={{fontSize:11}}/><Legend/></PieChart></ResponsiveContainer>;
  }
  if (catId === 'scatter') {
    return <ResponsiveContainer width="100%" height={h}><ScatterChart margin={{top:10,right:16,left:-10,bottom:10}}><CartesianGrid strokeDasharray="3 3" stroke="rgba(148,163,184,0.2)"/><XAxis dataKey={xKey} type="number" tick={{fontSize:9}} name={xKey}/><YAxis dataKey={yKey} type="number" tick={{fontSize:9}} name={yKey}/><Tooltip contentStyle={{fontSize:11}}/><Scatter data={data} fill={PALETTE[0]} fillOpacity={0.7}/></ScatterChart></ResponsiveContainer>;
  }
  if (catId === 'radar') {
    const pts = data.slice(0,8);
    return <ResponsiveContainer width="100%" height={h}><RadarChart data={pts} outerRadius="70%"><PolarGrid/><PolarAngleAxis dataKey={xKey} tick={{fontSize:9}}/><Radar dataKey={yKey} stroke={PALETTE[0]} fill={PALETTE[0]} fillOpacity={subtypeId==='filled'?0.5:0.25}/><Tooltip contentStyle={{fontSize:11}}/></RadarChart></ResponsiveContainer>;
  }
  if (catId === 'combo') {
    return <ResponsiveContainer width="100%" height={h}><ComposedChart {...commonProps}>{axis}<Bar dataKey={yKey} fill={PALETTE[0]} radius={[3,3,0,0]}/>{yKey2 && <Line type="monotone" dataKey={yKey2} stroke={PALETTE[3]} strokeWidth={2} dot={{r:2}}/>}<Legend/></ComposedChart></ResponsiveContainer>;
  }
  // histogram
  return <ResponsiveContainer width="100%" height={h}><BarChart {...commonProps}><CartesianGrid strokeDasharray="3 3" stroke="rgba(148,163,184,0.2)" vertical={false}/><XAxis dataKey={xKey} tick={{fontSize:9}} angle={-30} textAnchor="end"/><YAxis tick={{fontSize:9}} axisLine={false}/><Tooltip contentStyle={{fontSize:11}}/><Bar dataKey={yKey} fill={PALETTE[0]} radius={[3,3,0,0]}>{data.map((_,i)=><Cell key={i} fill={PALETTE[i%PALETTE.length]}/>)}</Bar></BarChart></ResponsiveContainer>;
}

// ── Build chart data from raw preview rows ────────────────────────
function buildData(rows, xKey, yKey, yKey2, maxRows = 20) {
  if (!rows?.length || !xKey || !yKey) return [];
  return rows.slice(0, maxRows).map(row => {
    const entry = { [xKey]: row[xKey] };
    const v = parseFloat(row[yKey]);
    entry[yKey] = isNaN(v) ? 0 : v;
    if (yKey2) { const v2 = parseFloat(row[yKey2]); entry[yKey2] = isNaN(v2) ? 0 : v2; }
    return entry;
  });
}

// ── Main Modal ────────────────────────────────────────────────────
export default function InsertChartModal({ columnNames = [], previewRows = [], onInsert, onClose }) {
  const [activeTab,  setActiveTab]  = useState('all');
  const [category,   setCategory]   = useState('column');
  const [subtype,    setSubtype]    = useState('clustered');
  const [xKey,       setXKey]       = useState(columnNames[0] || '');
  const [yKey,       setYKey]       = useState(columnNames[1] || columnNames[0] || '');
  const [yKey2,      setYKey2]      = useState('');
  const [chartTitle, setChartTitle] = useState('');

  const subtypeList = SUBTYPES[category] || [];

  const chartData = useMemo(
    () => buildData(previewRows, xKey, yKey, yKey2 || undefined),
    [previewRows, xKey, yKey, yKey2]
  );

  const handleCategoryChange = (id) => {
    setCategory(id);
    setSubtype(SUBTYPES[id]?.[0]?.id || '');
  };

  const handleInsert = () => {
    const cat  = CATEGORIES.find(c => c.id === category);
    const sub  = subtypeList.find(s => s.id === subtype);
    const title = chartTitle.trim() || `${sub?.label || cat?.label} — ${yKey} by ${xKey}`;
    onInsert({
      id:       `custom_${Date.now()}`,
      type:     category,
      subtype,
      title,
      data:     chartData,
      x_key:    xKey,
      y_key:    yKey,
      y_key2:   yKey2 || undefined,
      custom:   true,
    });
    onClose();
  };

  return createPortal(
    <div className="ict-overlay" onClick={onClose}>
      <div className="ict-dialog" onClick={e => e.stopPropagation()}>

        {/* Title bar */}
        <div className="ict-titlebar">
          <span className="ict-titlebar-text">Insert Chart</span>
          <button className="ict-close" onClick={onClose}>✕</button>
        </div>

        {/* Tabs */}
        <div className="ict-tabs">
          <button className={`ict-tab ${activeTab==='recommended'?'ict-tab--active':''}`} onClick={()=>setActiveTab('recommended')}>Recommended Charts</button>
          <button className={`ict-tab ${activeTab==='all'?'ict-tab--active':''}`} onClick={()=>setActiveTab('all')}>All Charts</button>
        </div>

        <div className="ict-body">
          {activeTab === 'all' && (
            <>
              {/* Left sidebar */}
              <div className="ict-sidebar">
                {CATEGORIES.map(cat => (
                  <button
                    key={cat.id}
                    className={`ict-cat-btn ${category===cat.id ? 'ict-cat-btn--active' : ''}`}
                    onClick={() => handleCategoryChange(cat.id)}
                  >
                    <span className="ict-cat-icon">{cat.icon}</span>
                    <span className="ict-cat-label">{cat.label}</span>
                  </button>
                ))}
              </div>

              {/* Right panel */}
              <div className="ict-panel">
                {/* Subtype row */}
                <div className="ict-subtypes">
                  {subtypeList.map(st => (
                    <div
                      key={st.id}
                      className={`ict-subtype-wrap ${subtype===st.id?'ict-subtype-wrap--active':''}`}
                      onClick={() => setSubtype(st.id)}
                      title={st.label}
                    >
                      <SubtypeThumb catId={category} subtypeId={st.id} active={subtype===st.id}/>
                    </div>
                  ))}
                </div>

                {/* Selected subtype label */}
                <div className="ict-subtype-name">
                  {subtypeList.find(s=>s.id===subtype)?.label || ''}
                </div>

                {/* Column pickers */}
                <div className="ict-axis-row">
                  <div className="ict-axis-group">
                    <label className="ict-axis-label">X Axis (Category)</label>
                    <select className="ict-select" value={xKey} onChange={e=>setXKey(e.target.value)}>
                      {columnNames.map(c=><option key={c} value={c}>{c}</option>)}
                    </select>
                  </div>
                  <div className="ict-axis-group">
                    <label className="ict-axis-label">Y Axis (Value)</label>
                    <select className="ict-select" value={yKey} onChange={e=>setYKey(e.target.value)}>
                      {columnNames.map(c=><option key={c} value={c}>{c}</option>)}
                    </select>
                  </div>
                  <div className="ict-axis-group">
                    <label className="ict-axis-label">Series 2 (optional)</label>
                    <select className="ict-select" value={yKey2} onChange={e=>setYKey2(e.target.value)}>
                      <option value="">— None —</option>
                      {columnNames.map(c=><option key={c} value={c}>{c}</option>)}
                    </select>
                  </div>
                  <div className="ict-axis-group">
                    <label className="ict-axis-label">Chart Title</label>
                    <input
                      className="ict-select"
                      placeholder="Auto-generated"
                      value={chartTitle}
                      onChange={e=>setChartTitle(e.target.value)}
                    />
                  </div>
                </div>

                {/* Live preview */}
                <div className="ict-preview-box">
                  <div className="ict-preview-label">Chart Preview</div>
                  <div className="ict-preview-wrapper">
                    <LivePreview catId={category} subtypeId={subtype} data={chartData} xKey={xKey} yKey={yKey} yKey2={yKey2||undefined}/>
                  </div>
                </div>
              </div>
            </>
          )}

          {activeTab === 'recommended' && (
            <div className="ict-recommended">
              {CATEGORIES.map(cat => (
                <button
                  key={cat.id}
                  className={`ict-rec-card ${category===cat.id?'ict-rec-card--active':''}`}
                  onClick={() => { handleCategoryChange(cat.id); setActiveTab('all'); }}
                >
                  <span className="ict-rec-icon">{cat.icon}</span>
                  <span className="ict-rec-label">{cat.label}</span>
                  <span className="ict-rec-desc">{SUBTYPES[cat.id]?.length} sub-types</span>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="ict-footer">
          <button className="ict-btn ict-btn--secondary" onClick={onClose}>Cancel</button>
          <button className="ict-btn ict-btn--primary" onClick={handleInsert} disabled={!xKey || !yKey}>
            Insert Chart
          </button>
        </div>
      </div>
    </div>,
    document.body
  );
}
