export default function AuthLayout({
	children,
}: {
	children: React.ReactNode;
}) {
	return (
		<div className="fixed inset-0 overflow-auto bg-marketing">{children}</div>
	);
}
