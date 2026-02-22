export default function SetupLayout({
	children,
}: {
	children: React.ReactNode;
}) {
	return (
		<div className="fixed inset-0 flex items-center justify-center bg-background p-4 overflow-hidden">
			{children}
		</div>
	);
}
