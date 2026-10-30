const base =
  'inline-flex items-center justify-center rounded-md px-3 py-1.5 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-60'

export const btn = {
  primary: `${base} bg-indigo-700 text-white hover:bg-indigo-800`,
  secondary: `${base} border border-slate-400 bg-white text-slate-900 hover:bg-slate-100`,
  danger: `${base} bg-red-700 text-white hover:bg-red-800`,
  ghost: `${base} text-indigo-800 hover:bg-indigo-50`,
}

export const inputClass =
  'block w-full rounded-md border border-slate-500 bg-white px-3 py-2 text-sm text-slate-900 placeholder:text-slate-600'

export const cardClass = 'rounded-lg border border-slate-300 bg-white p-4 shadow-sm'
