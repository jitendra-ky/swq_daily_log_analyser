import React from 'react';
import { IndianRupee, CreditCard, Banknote, Receipt, CheckCircle2 } from 'lucide-react';

const StatCard = ({ title, amount, subtitle, icon: Icon, trend }) => (
  <div className="bg-white rounded-2xl p-6 border border-slate-100 shadow-sm hover:shadow-md transition-shadow duration-200">
    <div className="flex justify-between items-start mb-4">
      <h3 className="text-xs font-bold text-slate-400 uppercase tracking-wider">{title}</h3>
      <div className="p-2 bg-slate-50 rounded-lg">
        <Icon className="w-5 h-5 text-slate-500" />
      </div>
    </div>
    <div className="flex items-baseline gap-1">
      <span className="text-3xl font-bold text-slate-800">
        ₹{(amount / 100).toLocaleString('en-IN')}
      </span>
    </div>
    <p className="text-xs font-medium text-slate-400 mt-2 flex items-center gap-1">
      {trend && <span className="text-emerald-500">{trend}</span>}
      {subtitle}
    </p>
  </div>
);

const DashboardView = ({ data }) => {
  if (!data) return null;

  return (
    <div className="max-w-6xl mx-auto animate-in fade-in slide-in-from-bottom-4 duration-500">
      <header className="mb-8">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold text-slate-800 tracking-tight">EOD Reconciliation</h1>
            <p className="text-sm text-slate-500 mt-1">
              {data.clinic_id} Clinic — Kanpur, Uttar Pradesh
            </p>
          </div>
          <div className="bg-white border border-slate-200 px-4 py-2 rounded-xl shadow-sm text-sm font-medium text-slate-600 flex items-center gap-2">
            <span>{new Date(data.report_date).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })}</span>
          </div>
        </div>
      </header>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
        <StatCard
          title="Total Billed"
          amount={data.total_billed_paise}
          subtitle={`${data.visit_count} visits`}
          icon={Receipt}
        />
        <StatCard
          title="Total Collected"
          amount={data.total_collected_paise}
          subtitle={`${Math.round((data.total_collected_paise / (data.total_billed_paise || 1)) * 100)}% of billed`}
          icon={IndianRupee}
          trend={Math.round((data.total_collected_paise / (data.total_billed_paise || 1)) * 100) > 80 ? 'Good' : null}
        />
        <StatCard
          title="Outstanding"
          amount={data.total_outstanding_paise}
          subtitle="pending visits"
          icon={Banknote}
        />
        <StatCard
          title="Refunds"
          amount={data.total_refunds_paise}
          subtitle={`${data.refund_count} refund(s)`}
          icon={CreditCard}
        />
      </div>

      <div className="bg-white rounded-3xl border border-slate-100 shadow-sm overflow-hidden">
        <div className="px-8 py-6 border-b border-slate-50">
          <h2 className="text-sm font-bold text-slate-800">Payment Mode Breakdown</h2>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-slate-50/50">
                <th className="px-8 py-4 text-xs font-semibold text-slate-500 uppercase tracking-wider">Mode</th>
                <th className="px-8 py-4 text-xs font-semibold text-slate-500 uppercase tracking-wider">Billed</th>
                <th className="px-8 py-4 text-xs font-semibold text-slate-500 uppercase tracking-wider">Collected</th>
                <th className="px-8 py-4 text-xs font-semibold text-slate-500 uppercase tracking-wider">Outstanding</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-50">
              {data.by_payment_mode?.map((mode) => (
                <tr key={mode.mode} className="hover:bg-slate-50/50 transition-colors duration-150">
                  <td className="px-8 py-5 text-sm font-semibold text-slate-700 capitalize">{mode.mode.toLowerCase()}</td>
                  <td className="px-8 py-5 text-sm text-slate-600">₹{(mode.billed_paise / 100).toLocaleString('en-IN')}</td>
                  <td className="px-8 py-5 text-sm text-slate-600">₹{(mode.collected_paise / 100).toLocaleString('en-IN')}</td>
                  <td className="px-8 py-5 text-sm text-slate-600">₹{(mode.outstanding_paise / 100).toLocaleString('en-IN')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};

export default DashboardView;
