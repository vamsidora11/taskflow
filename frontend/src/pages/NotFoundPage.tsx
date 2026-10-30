import { Link } from 'react-router-dom'
import { usePageTitle } from '../components/usePageTitle'

export default function NotFoundPage() {
  usePageTitle('Page not found')
  return (
    <main id="main" className="mx-auto max-w-md px-4 py-16 text-center">
      <h1 className="mb-2 text-2xl font-semibold">Page not found</h1>
      <p className="mb-4 text-slate-700">The page you are looking for does not exist.</p>
      <Link to="/" className="font-medium text-indigo-800 underline">
        Back to boards
      </Link>
    </main>
  )
}
