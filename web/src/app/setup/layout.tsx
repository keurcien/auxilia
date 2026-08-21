export default function SetupLayout({
	children,
}: {
	children: React.ReactNode;
}) {
	return (
		<div className="fixed inset-0 overflow-auto bg-marketing">{children}</div>
	);
}
