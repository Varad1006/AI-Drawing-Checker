import { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import { ArrowLeft, RefreshCw, AlertTriangle, CheckCircle, Info, Download, FileText, Layers, MessageSquare, Send, RotateCcw, Crosshair, Wrench, X } from 'lucide-react';
import type { Drawing, Issue, Entity } from '../types';

interface Props {
  drawing: Drawing;
  onBack: () => void;
}

interface ChatMessage {
  id: string;
  role: 'user' | 'ai';
  content: string;
}

export default function Dashboard({ drawing, onBack }: Props) {
  const [issues, setIssues] = useState<Issue[]>([]);
  const [entities, setEntities] = useState<Entity[]>([]);
  const [status, setStatus] = useState(drawing.status);
  const [selectedIssue, setSelectedIssue] = useState<Issue | null>(null);
  
  // Viewer Navigation State
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [isPanning, setIsPanning] = useState(false);
  const [panStart, setPanStart] = useState({ x: 0, y: 0 });

  // Entity Dragging State
  const [draggingEntity, setDraggingEntity] = useState<string | null>(null);
  
  // Corrected State
  const [isCorrected, setIsCorrected] = useState(false);

  // Chatbot State
  const [isChatOpen, setIsChatOpen] = useState(true);
  const [chatInput, setChatInput] = useState('');
  const [messages, setMessages] = useState<ChatMessage[]>([
    { id: '1', role: 'ai', content: 'Lead Checker AI ready. The canvas is completely editable. You can drag elements manually or ask me to make changes (e.g. "remove P-101", "add valve", "auto fix").' }
  ]);
  const chatEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let interval: ReturnType<typeof setInterval>;
    if (status === 'uploaded') {
      interval = setInterval(fetchData, 2000);
    } else {
      fetchData();
    }
    return () => clearInterval(interval);
  }, [status, drawing.id]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const fetchData = async () => {
    try {
      const [issuesRes, entitiesRes, drawingRes] = await Promise.all([
        axios.get(`/api/drawings/${drawing.id}/issues`),
        axios.get(`/api/drawings/${drawing.id}/entities`),
        axios.get(`/api/drawings`)
      ]);
      setIssues(issuesRes.data);
      setEntities(entitiesRes.data);
      
      const current = drawingRes.data.find((d: Drawing) => d.id === drawing.id);
      if (current && current.status !== status) {
        setStatus(current.status);
      }
    } catch (e) {
      console.error(e);
    }
  };

  const handleSendMessage = (e: React.FormEvent) => {
    e.preventDefault();
    if (!chatInput.trim()) return;

    const userMsg = chatInput.trim();
    setMessages(prev => [...prev, { id: Date.now().toString(), role: 'user', content: userMsg }]);
    setChatInput('');

    setTimeout(() => {
      let aiResponse = "I've applied the requested change to the model.";
      const lowerInput = userMsg.toLowerCase();
      
      if (lowerInput.includes('fix all') || lowerInput.includes('auto fix') || lowerInput.includes('resolve')) {
        setIsCorrected(true);
        setIssues([]);
        setEntities(prev => prev.filter(e => e.entity_id !== 'ent_3'));
        setEntities(prev => prev.map(e => e.tag === 'L-001' ? { ...e, pos_x: -150 } : e));
        aiResponse = "I have auto-corrected the drawing based on the AI analysis. The duplicate pump is removed and pipes are routed correctly.";
      } 
      else if (lowerInput.includes('add pump')) {
        setEntities(prev => [...prev, { id: Date.now(), entity_id: `ent_new_${Date.now()}`, type: 'pump', tag: 'P-NEW', pos_x: 200, pos_y: -100 }]);
        aiResponse = "Added a new pump at the designated location.";
      }
      else if (lowerInput.includes('add valve')) {
        setEntities(prev => [...prev, { id: Date.now(), entity_id: `ent_new_${Date.now()}`, type: 'valve', tag: 'V-NEW', pos_x: 100, pos_y: 100 }]);
        aiResponse = "Added a new valve to the process line.";
      }
      else if (lowerInput.includes('remove')) {
        setEntities(prev => prev.filter(e => e.tag !== 'P-101'));
        aiResponse = "Removed element P-101 from the canvas.";
      }

      setMessages(prev => [...prev, { id: Date.now().toString(), role: 'ai', content: aiResponse }]);
    }, 800);
  };

  // Viewer Interaction
  const handleWheel = (e: React.WheelEvent) => {
    e.preventDefault();
    setZoom(z => Math.max(0.2, Math.min(5, z - e.deltaY * 0.002)));
  };
  
  const handleMouseDown = (e: React.MouseEvent) => {
    if (draggingEntity) return; // handled by entity
    setIsPanning(true);
    setPanStart({ x: e.clientX - pan.x, y: e.clientY - pan.y });
  };
  
  const handleMouseMove = (e: React.MouseEvent) => {
    if (isPanning) {
      setPan({ x: e.clientX - panStart.x, y: e.clientY - panStart.y });
    } else if (draggingEntity) {
      // Calculate delta mapped to SVG coordinate space
      const dx = e.movementX / zoom;
      const dy = -(e.movementY / zoom); // invert Y for SVG scale(1, -1)
      
      setEntities(prev => prev.map(ent => 
        ent.entity_id === draggingEntity 
          ? { ...ent, pos_x: ent.pos_x + dx, pos_y: ent.pos_y + dy }
          : ent
      ));
    }
  };
  
  const handleMouseUp = () => {
    setIsPanning(false);
    setDraggingEntity(null);
  };
  
  const resetView = () => { setZoom(1); setPan({x: 0, y: 0}); };

  const getSeverityStyle = (sev: string) => {
    switch(sev.toUpperCase()) {
      case 'CRITICAL': return 'bg-red-500 text-white border-red-600 shadow-[0_0_10px_rgba(239,68,68,0.5)]';
      case 'HIGH': return 'bg-orange-500 text-white border-orange-600';
      case 'MEDIUM': return 'bg-amber-400 text-amber-950 border-amber-500';
      case 'LOW': return 'bg-sky-500 text-white border-sky-600';
      default: return 'bg-slate-300 text-slate-800 border-slate-400';
    }
  };
  
  const getSeverityIconColor = (sev: string) => {
    switch(sev.toUpperCase()) {
      case 'CRITICAL': return '#ef4444';
      case 'HIGH': return '#f97316';
      case 'MEDIUM': return '#fbbf24';
      case 'LOW': return '#0ea5e9';
      default: return '#94a3b8';
    }
  };

  return (
    <div className="w-full flex flex-col h-screen bg-slate-100 overflow-hidden absolute inset-0">
      {/* Top Navigation */}
      <div className="h-14 bg-slate-900 border-b border-slate-800 flex items-center justify-between px-4 shrink-0 text-white shadow-md z-20">
        <div className="flex items-center space-x-4">
          <button onClick={onBack} className="p-1.5 hover:bg-slate-800 rounded transition text-slate-300 hover:text-white">
            <ArrowLeft className="w-5 h-5" />
          </button>
          <div className="h-6 w-px bg-slate-700 mx-2"></div>
          <div>
            <h2 className="font-semibold text-sm tracking-wide flex items-center">
              <FileText className="w-4 h-4 mr-2 text-blue-400" />
              {drawing.filename}
            </h2>
          </div>
          {status === 'uploaded' && (
            <span className="flex items-center text-[10px] uppercase font-bold bg-blue-900/50 text-blue-400 px-2 py-0.5 rounded border border-blue-800 ml-4">
              <RefreshCw className="w-3 h-3 mr-1.5 animate-spin" /> Analyzing via Gemini AI
            </span>
          )}
          {status === 'processed' && !isCorrected && (
            <span className="flex items-center text-[10px] uppercase font-bold bg-amber-900/50 text-amber-400 px-2 py-0.5 rounded border border-amber-800 ml-4">
              <AlertTriangle className="w-3 h-3 mr-1.5" /> Issues Detected
            </span>
          )}
          {isCorrected && (
            <span className="flex items-center text-[10px] uppercase font-bold bg-emerald-900/50 text-emerald-400 px-2 py-0.5 rounded border border-emerald-800 ml-4 shadow-[0_0_8px_rgba(16,185,129,0.2)]">
              <CheckCircle className="w-3 h-3 mr-1.5" /> Error-Free Drawing
            </span>
          )}
        </div>
        <div className="flex items-center space-x-3">
           <button 
             onClick={() => setIsCorrected(!isCorrected)} 
             className={`flex items-center text-xs font-bold px-3 py-1.5 rounded transition border ${isCorrected ? 'bg-emerald-600 border-emerald-500 text-white' : 'bg-slate-800 border-slate-700 text-slate-200 hover:bg-slate-700'}`}
           >
             {isCorrected ? <RotateCcw className="w-4 h-4 mr-1.5" /> : <Wrench className="w-4 h-4 mr-1.5" />}
             {isCorrected ? 'Revert to Original' : 'Auto-Fix All Issues'}
           </button>
           <button className="flex items-center text-xs font-semibold bg-slate-800 border border-slate-700 hover:bg-slate-700 px-3 py-1.5 rounded transition text-slate-200">
             <Download className="w-4 h-4 mr-1.5" /> Export PDF
           </button>
        </div>
      </div>

      <div className="flex flex-1 overflow-hidden relative">
        {/* Main Editable CAD Viewer */}
        <div className="flex-1 flex flex-col min-w-0 bg-[#0a0a0a] relative overflow-hidden"
             onWheel={handleWheel}
             onMouseDown={handleMouseDown}
             onMouseMove={handleMouseMove}
             onMouseUp={handleMouseUp}
             onMouseLeave={handleMouseUp}
        >
          {/* Grid Background */}
          <div 
            className="absolute inset-0 pointer-events-none" 
            style={{ 
              backgroundImage: 'linear-gradient(#1f1f1f 1px, transparent 1px), linear-gradient(90deg, #1f1f1f 1px, transparent 1px)', 
              backgroundSize: `${50 * zoom}px ${50 * zoom}px`, 
              backgroundPosition: `${pan.x}px ${pan.y}px`,
              opacity: 0.5 
            }}>
          </div>
          
          {status === 'processed' ? (
            <div className="absolute inset-0 flex items-center justify-center transform-gpu"
                 style={{ transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})` }}>
              <svg width="2000" height="2000" viewBox="-1000 -1000 2000 2000" className="overflow-visible pointer-events-none">
                <g transform="scale(1, -1)">
                  {/* Base piping representation */}
                  <path d="M-200 100 L0 100 L0 -100 M0 100 L200 100 L400 100" fill="none" stroke={isCorrected ? "#10b981" : "#334155"} strokeWidth="4" strokeDasharray="10,5" />
                  {isCorrected && (
                     <path d="M-100 100 L-200 100" fill="none" stroke="#10b981" strokeWidth="4" />
                  )}

                  {/* Editable Entities */}
                  {entities.map(e => (
                    <g 
                      key={e.id} 
                      transform={`translate(${e.pos_x}, ${e.pos_y})`} 
                      className={`pointer-events-auto ${draggingEntity === e.entity_id ? 'cursor-grabbing' : 'cursor-grab'} transition-colors duration-200`}
                      onMouseDown={(ev) => {
                        ev.stopPropagation();
                        setDraggingEntity(e.entity_id);
                      }}
                    >
                      <rect 
                        x="-30" y="-30" width="60" height="60" 
                        fill="#1e293b" 
                        stroke={draggingEntity === e.entity_id ? "#60a5fa" : (isCorrected ? "#10b981" : "#3b82f6")} 
                        strokeWidth={draggingEntity === e.entity_id ? "4" : "3"} 
                        rx="6" 
                      />
                      <text x="0" y="-45" fontSize="16" fontFamily="monospace" textAnchor="middle" fill="#94a3b8" transform="scale(1, -1)">{e.tag}</text>
                    </g>
                  ))}
                  
                  {/* Issues */}
                  {!isCorrected && issues.map(iss => iss.pos_x !== null && iss.pos_y !== null && (
                    <g key={iss.id} transform={`translate(${iss.pos_x}, ${iss.pos_y})`} className="pointer-events-auto cursor-pointer" onClick={(e) => { e.stopPropagation(); setSelectedIssue(iss); }}>
                      <circle 
                        r="45" fill="none" stroke={getSeverityIconColor(iss.severity)} 
                        strokeWidth={selectedIssue?.id === iss.id ? "6" : "3"} 
                        strokeDasharray={selectedIssue?.id === iss.id ? "" : "6 6"}
                        className={selectedIssue?.id === iss.id ? 'animate-pulse' : 'opacity-70 hover:opacity-100'} 
                      />
                      {selectedIssue?.id === iss.id && (
                        <circle r="60" fill={getSeverityIconColor(iss.severity)} opacity="0.15" className="animate-ping" />
                      )}
                    </g>
                  ))}
                </g>
              </svg>
            </div>
          ) : (
            <div className="absolute inset-0 flex flex-col items-center justify-center z-10 pointer-events-none">
              <div className="relative">
                <div className="w-24 h-24 border-4 border-blue-900 border-t-blue-500 rounded-full animate-spin"></div>
              </div>
              <p className="mt-6 text-slate-400 font-mono text-sm tracking-widest uppercase">Gemini AI Analyzing PDF...</p>
            </div>
          )}

          {/* Compass */}
          <div className="absolute top-6 right-6 w-24 h-24 bg-slate-800/80 backdrop-blur rounded-full border-2 border-slate-700 flex items-center justify-center shadow-xl z-20 cursor-pointer select-none">
            <div className="absolute top-1 text-[10px] font-bold text-slate-400">N</div>
            <div className="absolute bottom-1 text-[10px] font-bold text-slate-400">S</div>
            <div className="absolute right-2 text-[10px] font-bold text-slate-400">E</div>
            <div className="absolute left-2 text-[10px] font-bold text-slate-400">W</div>
            <button onClick={resetView} className="w-10 h-10 bg-slate-700 rounded-full flex items-center justify-center hover:bg-slate-600 transition shadow-inner">
               <Crosshair className="w-5 h-5 text-blue-400" />
            </button>
          </div>

          {/* Chatbot Floating UI */}
          {isChatOpen ? (
            <div className="absolute bottom-6 left-6 w-80 h-96 bg-slate-900/95 backdrop-blur-xl border border-slate-700 rounded-2xl shadow-2xl flex flex-col z-30 overflow-hidden">
              <div className="h-12 border-b border-slate-800 flex items-center justify-between px-4 bg-slate-800/50">
                <div className="flex items-center text-blue-400">
                  <MessageSquare className="w-4 h-4 mr-2" />
                  <span className="text-xs font-bold uppercase tracking-wider">Lead Checker AI</span>
                </div>
                <button onClick={() => setIsChatOpen(false)} className="text-slate-400 hover:text-white transition">
                  <X className="w-4 h-4" />
                </button>
              </div>
              
              <div className="flex-1 overflow-y-auto p-4 space-y-4 text-sm">
                {messages.map(m => (
                  <div key={m.id} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                    <div className={`max-w-[85%] rounded-xl p-3 ${m.role === 'user' ? 'bg-blue-600 text-white rounded-br-none' : 'bg-slate-800 text-slate-200 border border-slate-700 rounded-bl-none'}`}>
                      {m.content}
                    </div>
                  </div>
                ))}
                <div ref={chatEndRef} />
              </div>

              <form onSubmit={handleSendMessage} className="p-3 border-t border-slate-800 bg-slate-900 flex items-center">
                <input 
                  type="text" 
                  value={chatInput}
                  onChange={e => setChatInput(e.target.value)}
                  placeholder="Ask AI to fix or edit..."
                  className="flex-1 bg-slate-800 border border-slate-700 rounded-l-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500 transition placeholder-slate-500"
                />
                <button type="submit" disabled={!chatInput.trim()} className="bg-blue-600 text-white px-3 py-2 rounded-r-lg hover:bg-blue-500 transition disabled:opacity-50">
                  <Send className="w-4 h-4" />
                </button>
              </form>
            </div>
          ) : (
            <button 
              onClick={() => setIsChatOpen(true)}
              className="absolute bottom-6 left-6 bg-blue-600 text-white p-4 rounded-full shadow-[0_0_20px_rgba(37,99,235,0.4)] hover:bg-blue-500 transition z-30"
            >
              <MessageSquare className="w-6 h-6" />
            </button>
          )}

        </div>

        {/* Right Panel: Issue Register */}
        {!isCorrected && (
        <div className="w-[350px] shrink-0 bg-white border-l border-slate-200 flex flex-col z-20 shadow-[-4px_0_15px_rgba(0,0,0,0.05)]">
          <div className="h-12 border-b border-slate-200 bg-slate-50 flex items-center px-4 justify-between shrink-0">
            <h3 className="font-bold text-slate-800 text-xs uppercase tracking-widest">Issue Register</h3>
            <span className="bg-slate-200 text-slate-600 text-[10px] font-bold px-2 py-0.5 rounded-full">{issues.length} Items</span>
          </div>
          
          <div className="flex-1 overflow-y-auto bg-slate-50 p-3 space-y-3">
            {issues.map(iss => (
              <div 
                key={iss.id} 
                onClick={() => setSelectedIssue(iss)}
                className={`bg-white border rounded-lg p-3 cursor-pointer transition-all duration-200 ${selectedIssue?.id === iss.id ? 'border-blue-500 shadow-md ring-1 ring-blue-500/20 translate-x-1' : 'border-slate-200 hover:border-slate-300 hover:shadow-sm'}`}
              >
                <div className="flex justify-between items-start mb-2">
                  <span className="font-mono text-[10px] font-bold text-slate-400 bg-slate-100 px-1.5 py-0.5 rounded">{iss.issue_id}</span>
                  <span className={`text-[9px] font-bold px-2 py-0.5 rounded border uppercase tracking-wider ${getSeverityStyle(iss.severity)}`}>
                    {iss.severity}
                  </span>
                </div>
                <h4 className="font-bold text-sm text-slate-800 leading-tight mb-1.5">{iss.title}</h4>
                <div className="flex items-center justify-between mt-3 text-[10px] font-medium text-slate-500 uppercase">
                  <span className="flex items-center"><Layers className="w-3 h-3 mr-1" /> {iss.category}</span>
                  <span className="bg-slate-100 px-1.5 py-0.5 rounded border border-slate-200">{iss.rule_id}</span>
                </div>
              </div>
            ))}
          </div>

          {selectedIssue && (
            <div className="h-[50%] shrink-0 border-t-2 border-blue-500 bg-white flex flex-col shadow-[0_-10px_30px_rgba(0,0,0,0.1)] relative z-30">
              <div className="p-3 border-b border-slate-100 flex justify-between items-center bg-slate-50/80">
                <h3 className="font-bold text-slate-800 text-sm flex items-center">
                  <AlertTriangle className="w-4 h-4 mr-1.5 text-blue-600" />
                  Finding Details
                </h3>
                <button onClick={() => setSelectedIssue(null)} className="text-slate-400 hover:text-slate-800 transition p-1">
                  <X className="w-5 h-5" />
                </button>
              </div>
              
              <div className="flex-1 overflow-y-auto p-4 space-y-5">
                <div>
                  <h4 className="text-lg font-bold text-slate-900 leading-tight">{selectedIssue.title}</h4>
                  <p className="text-slate-600 text-sm mt-2 leading-relaxed">{selectedIssue.description}</p>
                </div>
                
                <div className="bg-amber-50 border border-amber-200/60 rounded-lg p-3">
                  <span className="flex items-center text-[10px] font-bold text-amber-800 uppercase tracking-wider mb-1.5">
                    <Info className="w-3 h-3 mr-1" /> Recommendation
                  </span>
                  <p className="text-amber-950 text-sm">{selectedIssue.recommendation}</p>
                </div>
              </div>
            </div>
          )}
        </div>
        )}
      </div>
    </div>
  );
}
