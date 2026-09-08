export function CheckIcon(props) {
  return (
    <svg viewBox="0 0 20 20" fill="none" width="14" height="14" {...props}>
      <path d="M4 10.5L8 14.5L16 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function SpinnerIcon(props) {
  return (
    <svg viewBox="0 0 24 24" fill="none" width="14" height="14" className="spin" {...props}>
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="2.5" strokeOpacity="0.25" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
    </svg>
  );
}

export function UploadIcon(props) {
  return (
    <svg viewBox="0 0 24 24" fill="none" width="28" height="28" {...props}>
      <path d="M12 15V4M12 4L7.5 8.5M12 4l4.5 4.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function ArrowIcon(props) {
  return (
    <svg viewBox="0 0 20 20" fill="none" width="14" height="14" {...props}>
      <path d="M4 10h11M10 5l5 5-5 5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function TrashIcon(props) {
  return (
    <svg viewBox="0 0 20 20" fill="none" width="14" height="14" {...props}>
      <path
        d="M4 6h12M8 6V4.5A1.5 1.5 0 0 1 9.5 3h1A1.5 1.5 0 0 1 12 4.5V6m-6.5 0 .6 9.4a1.5 1.5 0 0 0 1.5 1.4h4.8a1.5 1.5 0 0 0 1.5-1.4L14.5 6"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function UserIcon(props) {
  return (
    <svg viewBox="0 0 20 20" fill="none" width="16" height="16" {...props}>
      <circle cx="10" cy="7" r="3.2" stroke="currentColor" strokeWidth="1.5" />
      <path
        d="M3.5 17c0-3.3 2.9-5.5 6.5-5.5s6.5 2.2 6.5 5.5"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
    </svg>
  );
}

export function RefreshIcon(props) {
  return (
    <svg viewBox="0 0 20 20" fill="none" width="13" height="13" {...props}>
      <path
        d="M16 10a6 6 0 1 1-1.76-4.24M16 3v4h-4"
        stroke="currentColor"
        strokeWidth="1.7"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
