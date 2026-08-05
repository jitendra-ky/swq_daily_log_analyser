export const generateReport = async (rawRows) => {
  const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '';
  const response = await fetch(`${API_BASE_URL}/api/v1/reports/generate/`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(rawRows),
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.error || `HTTP error! status: ${response.status}`);
  }

  return response.json();
};

export const fetchReport = async (clinicId, date) => {
  const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '';
  const response = await fetch(`${API_BASE_URL}/api/v1/reports/${clinicId}/${date}/`);

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.error || `HTTP error! status: ${response.status}`);
  }

  return response.json();
};
