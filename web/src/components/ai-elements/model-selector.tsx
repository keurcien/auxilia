import Image from "next/image";

import { cn } from "@/lib/utils";
import type { ComponentProps } from "react";

export type ModelSelectorLogoProps = Omit<
	ComponentProps<"img">,
	"src" | "alt"
> & {
	provider:
		| "moonshotai-cn"
		| "lucidquery"
		| "moonshotai"
		| "zai-coding-plan"
		| "alibaba"
		| "xai"
		| "vultr"
		| "nvidia"
		| "upstage"
		| "groq"
		| "github-copilot"
		| "mistral"
		| "vercel"
		| "nebius"
		| "deepseek"
		| "alibaba-cn"
		| "google-vertex-anthropic"
		| "venice"
		| "chutes"
		| "cortecs"
		| "github-models"
		| "togetherai"
		| "azure"
		| "baseten"
		| "huggingface"
		| "opencode"
		| "fastrouter"
		| "google"
		| "google-vertex"
		| "cloudflare-workers-ai"
		| "inception"
		| "wandb"
		| "openai"
		| "zhipuai-coding-plan"
		| "perplexity"
		| "openrouter"
		| "zenmux"
		| "v0"
		| "iflowcn"
		| "synthetic"
		| "deepinfra"
		| "zhipuai"
		| "submodel"
		| "zai"
		| "inference"
		| "requesty"
		| "morph"
		| "lmstudio"
		| "anthropic"
		| "aihubmix"
		| "fireworks-ai"
		| "modelscope"
		| "llama"
		| "scaleway"
		| "amazon-bedrock"
		| "cerebras"
		| "xiaomi"
		| "meta"
		| (string & {});
};

export const ModelSelectorLogo = ({
	provider,
	className,
	...props
}: ModelSelectorLogoProps) => (
	<Image
		{...props}
		alt={`${provider} logo`}
		className={cn("size-3", provider === "openai" && "dark:invert", className)}
		height={12}
		// src={`https://models.dev/logos/${provider}.svg`}
		src={`https://pub-7a6e8912b3c448b8a8bfa47a0363f7bc.r2.dev/assets/icons/${provider}.png`}
		width={12}
	/>
);
