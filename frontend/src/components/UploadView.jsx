import React, { useCallback, useState } from 'react';
import { UploadCloud, FileJson, Loader2 } from 'lucide-react';
import { generateReport } from '../api/client';

const UploadView = ({ onSuccess, isLoading, setIsLoading, error, setError }) => {
  const [dragActive, setDragActive] = useState(false);

  const handleDrag = (e) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === 'dragenter' || e.type === 'dragover') {
      setDragActive(true);
    } else if (e.type === 'dragleave') {
      setDragActive(false);
    }
  };

  const processFile = (file) => {
    if (!file) return;
    setError(null);
    setIsLoading(true);

    const reader = new FileReader();
    reader.onload = async (e) => {
      try {
        const json = JSON.parse(e.target.result);
        const report = await generateReport(json);
        onSuccess(report);
      } catch (err) {
        setError(err.message || 'Failed to parse JSON or generate report.');
        setIsLoading(false);
      }
    };
    reader.readAsText(file);
  };

  const handleDrop = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      processFile(e.dataTransfer.files[0]);
    }
  };

  const handleChange = (e) => {
    e.preventDefault();
    if (e.target.files && e.target.files[0]) {
      processFile(e.target.files[0]);
    }
  };

  return (
    <div className="max-w-md w-full bg-white rounded-3xl shadow-xl p-8 border border-slate-100">
      <div className="text-center mb-8">
        <h2 className="text-3xl font-bold text-slate-800 tracking-tight">Welcome to SwasthiQ</h2>
        <p className="text-slate-500 mt-2">Upload your daily billing log to generate insights.</p>
      </div>

      <div
        className={`relative group border-2 border-dashed rounded-2xl p-10 flex flex-col items-center justify-center transition-all duration-200 cursor-pointer ${
          dragActive
            ? 'border-blue-500 bg-blue-50/50'
            : 'border-slate-300 hover:border-blue-400 hover:bg-slate-50'
        }`}
        onDragEnter={handleDrag}
        onDragLeave={handleDrag}
        onDragOver={handleDrag}
        onDrop={handleDrop}
      >
        <input
          type="file"
          accept=".json,application/json"
          onChange={handleChange}
          className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
          disabled={isLoading}
        />
        {isLoading ? (
          <div className="flex flex-col items-center">
            <Loader2 className="w-10 h-10 text-blue-500 animate-spin mb-4" />
            <p className="text-sm font-medium text-blue-600">Generating report...</p>
          </div>
        ) : (
          <>
            <div className="bg-blue-100 text-blue-600 p-4 rounded-full mb-4 group-hover:scale-110 transition-transform duration-200">
              <UploadCloud className="w-8 h-8" />
            </div>
            <p className="text-sm font-medium text-slate-700">
              Drag & drop your JSON file here
            </p>
            <p className="text-xs text-slate-400 mt-1">or click to browse</p>
          </>
        )}
      </div>

      {error && (
        <div className="mt-6 p-4 bg-red-50 text-red-600 text-sm rounded-xl border border-red-100 flex items-start gap-3">
          <div className="mt-0.5 font-bold">!</div>
          <p>{error}</p>
        </div>
      )}
    </div>
  );
};

export default UploadView;
