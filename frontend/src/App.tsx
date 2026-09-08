import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { Upload, Loader2, FileText, ChevronRight, HardHat, Cpu, Workflow } from 'lucide-react';
import type { Drawing } from './types';
import Dashboard from './components/Dashboard';

function App() {
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [currentDrawing, setCurrentDrawing] = useState<Drawing | null>(null);
  const [drawings, setDrawings] = useState<Drawing[]>([]);

  useEffect(() => {
    fetchDrawings();
  }, []);

  const fetchDrawings = async () => {
    try {
      const res = await axios.get('/api/drawings');
      setDrawings(res.data);
    } catch (e) {
      console.error(e);
    }
  };

  const handleUpload = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!file) return;
    setUploading(true);
    const formData = new FormData();
    formData.append('file', file);
    try {
      const res = await axios.post('/api/drawings/upload', formData, {
        headers: { 'Content-Type': 'multipart/form-data' }
      });
      setCurrentDrawing(res.data);
      fetchDrawings();
    } catch (err) {
      console.error(err);
    } finally {
      setUploading(false);
    }
  };
  
  const runDemo = async () => {
    setUploading(true); 
    try { 
      const res = await axios.post("/api/drawings/demo"); 
      setCurrentDrawing(res.data); 
      fetchDrawings(); 
    } catch (e) {
      console.error(e);
    } finally { 
      setUploading(false); 
    }
  }

  if (currentDrawing) {
    return <Dashboard drawing={currentDrawing} onBack={() => setCurrentDrawing(null)} />;
  }

  return (
    <div className="min-h-screen bg-slate-950 flex flex-col font-sans text-slate-300 selection:bg-blue-500/30">
      {/* Navbar */}
      <header className="h-16 border-b border-slate-800 bg-slate-900/50 backdrop-blur flex items-center justify-between px-8 z-10 sticky top-0">
        <div className="flex items-center space-x-3">
          <div className="w-8 h-8 bg-blue-600 rounded flex items-center justify-center shadow-[0_0_15px_rgba(37,99,235,0.4)]">
            <HardHat className="w-5 h-5 text-white" />
          </div>
          <div>
            <h1 className="text-lg font-bold text-white tracking-wide flex items-center">
              LEAD CHECKER <span className="ml-2 px-1.5 py-0.5 rounded bg-blue-900/50 text-blue-400 text-[10px] uppercase border border-blue-800">POC</span>
            </h1>
          </div>
        </div>
        <div className="flex space-x-6 text-sm font-medium text-slate-400">
          <span className="hover:text-white cursor-pointer transition">Documentation</span>
          <span className="hover:text-white cursor-pointer transition">Rules Engine</span>
          <span className="hover:text-white cursor-pointer transition">Settings</span>
        </div>
      </header>
      
      <main className="flex-1 flex flex-col items-center justify-center p-6 relative overflow-hidden">
        {/* Background Decorative Elements */}
        <div className="absolute top-[-20%] left-[-10%] w-[50%] h-[50%] rounded-full bg-blue-900/10 blur-[120px] pointer-events-none"></div>
        <div className="absolute bottom-[-20%] right-[-10%] w-[50%] h-[50%] rounded-full bg-slate-800/30 blur-[120px] pointer-events-none"></div>

        <div className="max-w-5xl w-full grid grid-cols-1 md:grid-cols-2 gap-12 items-center z-10">
          
          {/* Left Column: Copy */}
          <div className="space-y-6">
            <h2 className="text-4xl md:text-5xl font-extrabold text-white leading-tight">
              Automated QA for <br/><span className="text-transparent bg-clip-text bg-gradient-to-r from-blue-400 to-cyan-300">Engineering Drawings</span>
            </h2>
            <p className="text-lg text-slate-400 leading-relaxed max-w-lg">
              Upload P&IDs and mechanical drawings. Our AI-assisted rule engine extracts CAD topology to detect tagging errors, missing connections, and specification mismatches instantly.
            </p>
            
            <div className="flex flex-col space-y-4 pt-4">
              <div className="flex items-center space-x-3 text-slate-300 bg-slate-900/50 p-3 rounded-lg border border-slate-800 w-max">
                <Cpu className="w-5 h-5 text-blue-400" />
                <span className="font-medium text-sm">Deterministic Rule Engine</span>
              </div>
              <div className="flex items-center space-x-3 text-slate-300 bg-slate-900/50 p-3 rounded-lg border border-slate-800 w-max">
                <Workflow className="w-5 h-5 text-emerald-400" />
                <span className="font-medium text-sm">Topological Graph Analysis</span>
              </div>
            </div>
          </div>

          {/* Right Column: Upload Card */}
          <div className="bg-slate-900 border border-slate-800 rounded-2xl shadow-2xl p-8 relative overflow-hidden">
            <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-blue-500 to-cyan-400"></div>
            
            <h3 className="text-xl font-bold text-white mb-2">New Inspection</h3>
            <p className="text-sm text-slate-400 mb-6">Upload an AutoCAD DXF or PDF to begin.</p>
            
            <form onSubmit={handleUpload} className="space-y-4">
              <div className="border-2 border-dashed border-slate-700 bg-slate-950/50 rounded-xl p-12 flex flex-col items-center justify-center text-center hover:border-blue-500/50 hover:bg-slate-900 transition-all group relative">
                <Upload className="w-10 h-10 text-slate-500 mb-4 group-hover:text-blue-400 transition-colors" />
                <input 
                  type="file" 
                  accept=".dxf,.pdf"
                  className="absolute inset-0 w-full h-full opacity-0 cursor-pointer" 
                  id="file-upload" 
                  onChange={(e) => setFile(e.target.files?.[0] || null)}
                />
                {file ? (
                  <div className="flex flex-col items-center">
                    <span className="text-blue-400 font-medium">{file.name}</span>
                    <span className="text-xs text-slate-500 mt-1">{(file.size / 1024 / 1024).toFixed(2)} MB</span>
                  </div>
                ) : (
                  <>
                    <span className="text-slate-300 font-medium">Drag & drop your file here</span>
                    <span className="text-xs text-slate-500 mt-2">or click to browse</span>
                  </>
                )}
              </div>
              
              <div className="grid grid-cols-2 gap-4 pt-2">
                <button 
                  type="button" 
                  onClick={runDemo}
                  disabled={uploading}
                  className="bg-slate-800 text-slate-300 py-3.5 rounded-lg font-medium hover:bg-slate-700 hover:text-white transition disabled:opacity-50 border border-slate-700 flex items-center justify-center text-sm"
                >
                  {uploading && !file ? <Loader2 className="w-4 h-4 animate-spin mr-2" /> : 'Run Live Demo'}
                </button>
                <button 
                  type="submit" 
                  disabled={!file || uploading}
                  className="bg-blue-600 text-white py-3.5 rounded-lg font-bold hover:bg-blue-500 shadow-[0_0_15px_rgba(37,99,235,0.3)] transition disabled:opacity-50 disabled:shadow-none flex items-center justify-center text-sm"
                >
                  {uploading && file ? <Loader2 className="w-4 h-4 animate-spin mr-2" /> : 'Analyze Drawing'}
                </button>
              </div>
            </form>
          </div>
        </div>

        {/* Recent Inspections - Full width at bottom */}
        {drawings.length > 0 && (
          <div className="w-full max-w-5xl mt-16 z-10">
            <h3 className="text-xs font-bold text-slate-500 uppercase tracking-widest mb-4">Recent Inspections</h3>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              {drawings.slice(0, 3).map(d => (
                <div 
                  key={d.id} 
                  className="bg-slate-900 border border-slate-800 rounded-lg p-4 cursor-pointer hover:border-slate-600 hover:bg-slate-800/80 transition group flex items-center justify-between" 
                  onClick={() => setCurrentDrawing(d)}
                >
                  <div className="flex items-center overflow-hidden">
                    <FileText className="w-8 h-8 text-slate-600 group-hover:text-blue-400 mr-3 shrink-0 transition-colors" />
                    <div className="truncate">
                      <h4 className="text-sm font-medium text-slate-300 truncate">{d.filename}</h4>
                      <span className="text-[10px] text-slate-500 uppercase mt-0.5 block">{d.status}</span>
                    </div>
                  </div>
                  <ChevronRight className="w-4 h-4 text-slate-600 group-hover:text-slate-400 shrink-0" />
                </div>
              ))}
            </div>
          </div>
        )}
      </main>
    </div>
  );
}

export default App;
