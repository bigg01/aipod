{{/* Base name, overridable. */}}
{{- define "aipod.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/* Fully qualified release name. */}}
{{- define "aipod.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "aipod.serverName" -}}{{ include "aipod.fullname" . }}-server{{- end -}}
{{- define "aipod.agentName" -}}{{ include "aipod.fullname" . }}-agent{{- end -}}
{{- define "aipod.configName" -}}{{ include "aipod.fullname" . }}-config{{- end -}}

{{- define "aipod.authSecretName" -}}
{{- if .Values.auth.existingSecret -}}{{ .Values.auth.existingSecret }}{{- else -}}{{ include "aipod.fullname" . }}-auth{{- end -}}
{{- end -}}

{{- define "aipod.modelSecretName" -}}
{{- if .Values.model.existingSecret -}}{{ .Values.model.existingSecret }}{{- else -}}{{ include "aipod.fullname" . }}-model{{- end -}}
{{- end -}}

{{- define "aipod.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "aipod.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{- define "aipod.image" -}}
{{- printf "%s:%s" .Values.image.repository (default .Chart.AppVersion .Values.image.tag) -}}
{{- end -}}

{{/* agent -> server MCP URL, computed when config.AIPOD_MCP_URL is empty. */}}
{{- define "aipod.mcpUrl" -}}
{{- if .Values.config.AIPOD_MCP_URL -}}
{{- .Values.config.AIPOD_MCP_URL -}}
{{- else -}}
{{- printf "http://%s.%s.svc.cluster.local:%d/mcp" (include "aipod.serverName" .) .Release.Namespace (int .Values.server.service.port) -}}
{{- end -}}
{{- end -}}

{{- define "aipod.commonLabels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
app.kubernetes.io/name: {{ include "aipod.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- with .Chart.AppVersion }}
app.kubernetes.io/version: {{ . | quote }}
{{- end }}
{{- end -}}

{{- define "aipod.selectorLabels" -}}
app.kubernetes.io/name: {{ include "aipod.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{/* OpenTelemetry metrics env, shared by both modes. Empty when metrics.exporter is "". */}}
{{- define "aipod.metricsEnv" -}}
{{- with .Values.metrics.exporter }}
- name: AIPOD_METRICS
  value: {{ . | quote }}
{{- end }}
{{- with .Values.metrics.otlpEndpoint }}
- name: OTEL_EXPORTER_OTLP_ENDPOINT
  value: {{ . | quote }}
{{- end }}
{{- with .Values.metrics.resourceAttributes }}
- name: OTEL_RESOURCE_ATTRIBUTES
  value: {{ . | quote }}
{{- end }}
{{- end -}}

{{/* Prometheus scrape annotations for a pod on the given container port. */}}
{{- define "aipod.scrapeAnnotations" -}}
{{- if and (eq .exporter "prometheus") .enabled }}
prometheus.io/scrape: "true"
prometheus.io/path: "/metrics"
prometheus.io/port: "{{ .port }}"
{{- end }}
{{- end -}}
