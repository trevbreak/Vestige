/**
 * Debug bootstrap — imported once at the top of main.jsx.
 *
 * When VITE_DEBUG_MODE=true this installs three global hooks that print every
 * error to the browser's developer-tools console with full stack traces:
 *
 *   1. window.onerror          — uncaught synchronous JS errors
 *   2. unhandledrejection      — unhandled Promise rejections
 *   3. console.error intercept — every explicit console.error() call
 *
 * Toggle by setting VITE_DEBUG_MODE in your .env file (restart `npm run dev`
 * after changing it).
 */

const DEBUG = import.meta.env.VITE_DEBUG_MODE === 'true'

export function installDebugHooks() {
  if (!DEBUG) return

  const tag = '[Vestige DEBUG]'

  // 1. Uncaught synchronous errors
  window.onerror = (message, source, lineno, colno, error) => {
    console.group(`${tag} Uncaught error`)
    console.error('Message :', message)
    console.error('Source  :', source, `${lineno}:${colno}`)
    if (error?.stack) console.error('Stack   :\n' + error.stack)
    console.groupEnd()
    return false  // let the browser still report it
  }

  // 2. Unhandled Promise rejections
  window.addEventListener('unhandledrejection', (event) => {
    const reason = event.reason
    console.group(`${tag} Unhandled Promise rejection`)
    console.error('Reason  :', reason)
    if (reason?.stack) console.error('Stack   :\n' + reason.stack)
    console.groupEnd()
  })

  // 3. Intercept console.error to add stack traces
  const _origError = console.error.bind(console)
  console.error = (...args) => {
    _origError(`${tag}`, ...args)
    const stack = new Error().stack?.split('\n').slice(2).join('\n')
    if (stack) _origError('  at:\n' + stack)
  }

  console.info(`${tag} Debug mode active — all errors will be verbose`)
}
