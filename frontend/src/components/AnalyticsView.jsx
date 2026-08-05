import React from 'react';
import { BarChart, Bar, XAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts';

const AnalyticsView = ({ data }) => {
  if (!data) return null;

  // Format chart data
  const chartData = data.revenue_by_hour?.map(item => ({
    name: item.hour > 12 ? `${item.hour - 12}pm` : item.hour === 12 ? '12pm' : `${item.hour}am`,
    revenue: item.revenue_paise / 100,
    isPeak: data.peak_hour && data.peak_hour.hour === item.hour
  })) || [];

  return (
    <div className="max-w-6xl mx-auto animate-in fade-in slide-in-from-bottom-4 duration-500">
      <header className="mb-8">
        <h1 className="text-3xl font-bold text-slate-800 tracking-tight">Analytics</h1>
        <p className="text-sm text-slate-500 mt-1">
          {data.clinic_id} Clinic — {new Date(data.report_date).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })}
        </p>
      </header>

      <div className="bg-white rounded-3xl border border-slate-100 shadow-sm p-8 mb-6">
        <div className="flex justify-between items-end mb-6">
          <h2 className="text-sm font-bold text-slate-800">Revenue by Hour of Day</h2>
          {data.peak_hour && (
            <div className="text-xs font-semibold text-blue-600 bg-blue-50 px-3 py-1 rounded-full">
              Peak: {data.peak_hour.hour > 12 ? data.peak_hour.hour - 12 : data.peak_hour.hour}{data.peak_hour.hour >= 12 ? 'pm' : 'am'} — ₹{(data.peak_hour.revenue_paise / 100).toLocaleString('en-IN')}
            </div>
          )}
        </div>
        
        <div className="h-64 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chartData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
              <XAxis 
                dataKey="name" 
                axisLine={false} 
                tickLine={false} 
                tick={{ fill: '#94a3b8', fontSize: 12 }} 
                dy={10}
              />
              <Tooltip 
                cursor={{ fill: '#f8fafc' }}
                contentStyle={{ borderRadius: '12px', border: 'none', boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.1)' }}
                formatter={(value) => [`₹${value.toLocaleString('en-IN')}`, 'Revenue']}
              />
              <Bar dataKey="revenue" radius={[6, 6, 6, 6]}>
                {chartData.map((entry, index) => (
                  <Cell key={`cell-${index}`} fill={entry.isPeak ? '#2563eb' : '#bfdbfe'} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Top by Quantity */}
        <div className="bg-white rounded-3xl border border-slate-100 shadow-sm p-8">
          <h2 className="text-sm font-bold text-slate-800 mb-6">Top Medicines — by Quantity</h2>
          <div className="space-y-4">
            {data.top_by_quantity?.slice(0, 5).map((item, index) => (
              <div key={item.drug_name} className="flex items-center justify-between group">
                <div className="flex items-center gap-4">
                  <span className="text-xs font-bold text-slate-400 w-4">{index + 1}</span>
                  <span className="text-sm font-semibold text-slate-700">{item.drug_name}</span>
                </div>
                <span className="text-sm text-slate-500">{item.value} units</span>
              </div>
            ))}
          </div>
        </div>

        {/* Top by Revenue */}
        <div className="bg-white rounded-3xl border border-slate-100 shadow-sm p-8">
          <h2 className="text-sm font-bold text-slate-800 mb-6">Top Medicines — by Revenue</h2>
          <div className="space-y-4">
            {data.top_by_revenue?.slice(0, 5).map((item, index) => (
              <div key={item.drug_name} className="flex items-center justify-between group">
                <div className="flex items-center gap-4">
                  <span className="text-xs font-bold text-slate-400 w-4">{index + 1}</span>
                  <span className="text-sm font-semibold text-slate-700">{item.drug_name}</span>
                </div>
                <span className="text-sm text-slate-500">₹{(item.value / 100).toLocaleString('en-IN')}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};

export default AnalyticsView;
