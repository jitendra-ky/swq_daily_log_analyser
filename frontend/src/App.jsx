import React, { useState } from 'react';
import Sidebar from './components/Sidebar';
import DashboardView from './components/DashboardView';
import AnalyticsView from './components/AnalyticsView';
import NarrativeView from './components/NarrativeView';
import UploadView from './components/UploadView';

function App() {
  const [reportData, setReportData] = useState(null);
  const [activeTab, setActiveTab] = useState('dashboard'); // 'dashboard', 'analytics', 'narrative'
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);

  const handleReportGenerated = (data) => {
    setReportData(data);
    setActiveTab('dashboard');
  };

  const renderContent = () => {
    switch (activeTab) {
      case 'dashboard':
        return <DashboardView data={reportData.recon_report} />;
      case 'analytics':
        return <AnalyticsView data={reportData.analytics_report} />;
      case 'narrative':
        return <NarrativeView data={reportData.narrative_result} />;
      default:
        return <DashboardView data={reportData.recon_report} />;
    }
  };

  return (
    <div className="flex h-screen w-full bg-slate-50 overflow-hidden text-slate-900 font-sans">
      {!reportData ? (
        <div className="flex w-full items-center justify-center">
          <UploadView 
            onSuccess={handleReportGenerated} 
            isLoading={isLoading} 
            setIsLoading={setIsLoading} 
            error={error} 
            setError={setError} 
          />
        </div>
      ) : (
        <>
          <Sidebar activeTab={activeTab} setActiveTab={setActiveTab} />
          <main className="flex-1 h-full overflow-y-auto p-8">
            {renderContent()}
          </main>
        </>
      )}
    </div>
  );
}

export default App;
