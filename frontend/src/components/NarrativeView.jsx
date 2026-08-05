import React from 'react';
import { CheckCircle2 } from 'lucide-react';

const NarrativeView = ({ data }) => {
  if (!data) return null;

  return (
    <div className="max-w-6xl mx-auto animate-in fade-in slide-in-from-bottom-4 duration-500 h-full flex flex-col">
      <header className="mb-6 flex items-center gap-3">
        <h1 className="text-3xl font-bold text-slate-800 tracking-tight">AI Narrative Summary</h1>
        <span className="px-2.5 py-1 rounded-md bg-purple-100 text-purple-700 text-[10px] font-bold tracking-widest uppercase">
          AI Suggested
        </span>
      </header>

      <div className="flex flex-col lg:flex-row gap-6 flex-1 min-h-0">
        
        {/* Narrative Panel */}
        <div className="flex-1 bg-green-50/50 rounded-3xl border border-green-100 p-8 flex flex-col">
          <div className="mb-6 text-xs font-bold text-slate-500 uppercase tracking-wider">
            Sent to: Dr. Anand Mehta · WhatsApp
          </div>
          
          <div className="flex-1 overflow-y-auto pr-4">
            <div className="text-slate-800 leading-relaxed space-y-6 whitespace-pre-wrap text-[15px]">
              {data.text}
            </div>
          </div>
          
          <div className="mt-8 pt-6 border-t border-green-200/50 flex items-center gap-2">
            <div className="flex items-center gap-1.5 px-3 py-1 bg-green-100 text-green-700 rounded-full text-xs font-bold uppercase tracking-wider">
              <CheckCircle2 className="w-3.5 h-3.5" />
              Success
            </div>
            <span className="text-xs text-slate-400">Generated successfully</span>
          </div>
        </div>

        {/* Traced Figures Panel */}
        <div className="w-full lg:w-96 bg-white rounded-3xl border border-slate-200 shadow-sm p-8 flex flex-col">
          <div className="mb-6">
            <h2 className="text-sm font-bold text-slate-800">Traced Figures</h2>
            <p className="text-xs text-slate-500 mt-1">Every number above maps to the deterministic report — this is what gets auto-checked.</p>
          </div>
          
          <div className="flex-1 overflow-y-auto pr-2 space-y-4">
            {data.traced_figures?.map((figure, idx) => (
              <div key={idx} className="flex justify-between items-center group py-1">
                <span className="text-sm font-bold text-slate-800 group-hover:text-blue-600 transition-colors">
                  {figure.display_value}
                </span>
                <span className="text-xs font-mono text-blue-500/70 bg-blue-50 px-2 py-1 rounded">
                  {figure.source_field}
                </span>
              </div>
            ))}
            
            {(!data.traced_figures || data.traced_figures.length === 0) && (
              <div className="text-sm text-slate-400 italic text-center mt-10">
                No figures traced.
              </div>
            )}
          </div>
        </div>

      </div>
    </div>
  );
};

export default NarrativeView;
