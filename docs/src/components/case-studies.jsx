import { getPageMap } from "nextra/page-map";

/**
 * Case studies — a Medium-like section: cards on the index, a wide article
 * column with a byline header inside. Server components: the card list reads
 * each article's frontmatter from the page map, so adding a case study is one
 * MDX file with frontmatter plus a `_meta.js` entry.
 */

const formatDate = (value) =>
	value
		? new Date(value).toLocaleDateString("en-US", {
				month: "short",
				day: "numeric",
				year: "numeric",
			})
		: null;

const initials = (name = "") =>
	name
		.split(/\s+/)
		.filter(Boolean)
		.slice(0, 2)
		.map((part) => part[0].toUpperCase())
		.join("");

function Byline({ author, authorRole, date, readingTime, size = "sm" }) {
	const meta = [formatDate(date), readingTime].filter(Boolean).join(" · ");
	return (
		<div className={`pm-cs-byline pm-cs-byline-${size}`}>
			<span className="pm-cs-avatar" aria-hidden="true">
				{initials(author) || "·"}
			</span>
			<span className="pm-cs-byline-text">
				<span className="pm-cs-author">
					{author}
					{authorRole && <span className="pm-cs-author-role"> · {authorRole}</span>}
				</span>
				{meta && <span className="pm-cs-meta">{meta}</span>}
			</span>
		</div>
	);
}

function Tags({ tags }) {
	if (!tags?.length) return null;
	return (
		<div className="pm-cs-tags">
			{tags.map((tag) => (
				<span key={tag} className="pm-cs-tag">
					{tag}
				</span>
			))}
		</div>
	);
}

export function CaseStudiesHero() {
	return (
		<header className="pm-cs-hero">
			<div className="pm-eyebrow">{"// CASE STUDIES"}</div>
			<h1 className="pm-cs-hero-title">Built on auxilia</h1>
			<p className="pm-cs-hero-sub">
				Real builds, written up end to end: what the agent looked like, which
				tools and skills it used, and what it took to make it useful.
			</p>
		</header>
	);
}

/** One card per article under /case-studies, newest first. */
export async function CaseStudyCards() {
	const items = await getPageMap("/case-studies");
	const articles = items
		.filter((item) => item.frontMatter && item.route && item.name !== "index")
		.sort((a, b) => String(b.frontMatter.date ?? "").localeCompare(String(a.frontMatter.date ?? "")));

	if (articles.length === 0) {
		return <p className="pm-cs-empty">No case study yet — be the first to write one below.</p>;
	}

	return (
		<div className="pm-cs-grid">
			{articles.map(({ route, frontMatter: fm }) => (
				<a key={route} href={route} className="pm-cs-card">
					<div className="pm-cs-cover">
						{fm.image && <img src={fm.image} alt={fm.imageAlt ?? ""} loading="lazy" />}
					</div>
					<div className="pm-cs-card-body">
						<Tags tags={fm.tags} />
						<h2 className="pm-cs-card-title">{fm.title}</h2>
						{fm.description && <p className="pm-cs-card-desc">{fm.description}</p>}
						<Byline
							author={fm.author}
							authorRole={fm.authorRole}
							date={fm.date}
							readingTime={fm.readingTime}
						/>
					</div>
				</a>
			))}
		</div>
	);
}

/** Article masthead — spread the page's `metadata` (its frontmatter) into it. */
export function ArticleHeader({
	title,
	description,
	author,
	authorRole,
	date,
	readingTime,
	tags,
	image,
	imageAlt,
}) {
	return (
		<header className="pm-article-header">
			<a href="/case-studies" className="pm-cs-back">
				← Case studies
			</a>
			<Tags tags={tags} />
			<h1 className="pm-article-title">{title}</h1>
			{description && <p className="pm-article-sub">{description}</p>}
			<Byline author={author} authorRole={authorRole} date={date} readingTime={readingTime} size="lg" />
			{image && (
				<figure className="pm-article-cover">
					<img src={image} alt={imageAlt ?? ""} />
					{imageAlt && <figcaption>{imageAlt}</figcaption>}
				</figure>
			)}
		</header>
	);
}
