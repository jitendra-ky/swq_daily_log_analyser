import React from 'react';
import { LayoutDashboard, BarChart3, MessageSquareText } from 'lucide-react';

const Sidebar = ({ activeTab, setActiveTab }) => {
  const navItems = [
    { id: 'dashboard', label: 'EOD Reconciliation', icon: LayoutDashboard },
    { id: 'analytics', label: 'Analytics', icon: BarChart3 },
    { id: 'narrative', label: 'AI Narrative Summary', icon: MessageSquareText },
  ];

  return (
    <aside className="w-64 bg-white border-r border-slate-200 h-full flex flex-col pt-6 pb-4">
      <div className="px-6 mb-8 flex items-center">
        <h1 className="text-2xl font-bold text-blue-600 flex items-center gap-2">
          Swasthi<span className="text-teal-500">Q</span>
        </h1>
      </div>
      <nav className="flex-1 px-4 space-y-2">
        {navItems.map((item) => {
          const isActive = activeTab === item.id;
          const Icon = item.icon;
          return (
            <button
              key={item.id}
              onClick={() => setActiveTab(item.id)}
              className={`w-full flex items-center gap-3 px-4 py-3 rounded-xl transition-all duration-200 text-sm font-medium ${
                isActive
                  ? 'bg-blue-50 text-blue-700 shadow-sm ring-1 ring-blue-100'
                  : 'text-slate-600 hover:bg-slate-50 hover:text-slate-900'
              }`}
            >
              <Icon className={`w-5 h-5 ${isActive ? 'text-blue-600' : 'text-slate-400'}`} />
              {item.label}
            </button>
          );
        })}
      </nav>
      <div className="px-6 mt-auto">
        <p className="text-xs text-slate-400">© 2026 SwasthiQ</p>
      </div>
    </aside>
  );
};

export default Sidebar;
