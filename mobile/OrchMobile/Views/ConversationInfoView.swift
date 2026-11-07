import SwiftUI
import ImageIO
import UIKit

@MainActor
struct ConversationInfoView: View {
    let conversation: ConversationID

    @Environment(AppModel.self) private var model
    @Environment(\.openURL) private var openURL
    @State private var selection: InfoGroup = .photos
    @State private var viewer: ArtifactItem?
    @State private var preview: InfoPreview?
    @State private var previewFolder: URL?
    @State private var loadingFile = false
    @State private var fileError: String?

    init(conversation: ConversationID) { self.conversation = conversation }

    private var workspaceName: String {
        model.workspace(conversation.workspace)?.displayName ?? conversation.workspace
    }

    private var topic: TopicSummary? {
        model.workspaceSummaries.first { $0.id == conversation.workspace }?
            .topics.first { $0.id == conversation }
    }

    private var ticket: Ticket? {
        guard let id = conversation.ticket else { return nil }
        return model.ticket(conversation.workspace, id)
    }

    private var title: String {
        if case .general = conversation { return "General - \(workspaceName)" }
        let name = topic?.title ?? ticket?.displayTitle ?? "Starting topic…"
        if let key = topic?.key ?? ticket?.key { return "\(key) · \(name)" }
        return name
    }

    private var summary: String {
        if case .general = conversation { return "Your ongoing conversation with \(workspaceName)" }
        let status = topic?.status.label ?? ticket.map { TopicStatus($0).label } ?? "Working"
        let snapshot = ticket?.view
        let done = snapshot?.done ?? snapshot.flatMap { $0.checklist.isEmpty ? nil : $0.checklist.filter(\.done).count }
        return done.map { "\($0) tasks complete - \(status)" } ?? status
    }

    private var entries: [InfoEntry] {
        InfoGrouping.entries(messages: model.conversationItems(conversation), ticketAttachments: ticket?.view?.attachments ?? [],
                             ticketAt: ticket?.at ?? "", conversation: conversation)
    }

    private var refs: [TicketRef] { ticket?.view?.refs ?? [] }

    private var referenceRows: [RefRow] {
        RefRow.rows(refs, lookup: { id in
            model.ticket(conversation.workspace, id).map { (key: $0.key, title: $0.displayTitle) }
        }, attachments: { ticketId, name in
            model.ticket(conversation.workspace, ticketId)?.view?.attachments
                .first { $0.name == name || $0.title == name }
                .map { ArtifactItem($0, in: .topic(workspace: conversation.workspace, ticket: ticketId)) }
        })
    }

    private func remainingLinks(_ all: [InfoEntry], rows: [RefRow]) -> [InfoEntry] {
        let urls = Set(rows.compactMap { row -> URL? in
            if case .link(_, _, _, let url) = row { return url }
            return nil
        })
        return entries(in: .links, from: all).filter { entry in
            guard let url = entry.item.url else { return true }
            return !urls.contains(url)
        }
    }

    private func entries(in group: InfoGroup, from all: [InfoEntry]) -> [InfoEntry] { InfoGrouping.entries(in: group, from: all) }

    var body: some View {
        let all = entries
        let references = referenceRows
        let links = remainingLinks(all, rows: references)
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                header
                VStack(alignment: .leading, spacing: 8) {
                    Text("SUMMARY").themeFont(12).foregroundStyle(Theme.muted)
                    Text(summary).themeFont(15)
                        .frame(maxWidth: .infinity, minHeight: 44, alignment: .leading)
                        .padding(.horizontal, 16).padding(.vertical, 5)
                        .background(Theme.surface2, in: RoundedRectangle(cornerRadius: 14))
                        .accessibilityIdentifier("info-summary")
                }
                VStack(spacing: 16) {
                    segments(all, referenceCount: references.count + links.count)
                    if selection == .links { referenceContent(references, links: links) }
                    else { content(entries(in: selection, from: all)) }
                }
            }
            .padding(16).padding(.top, 8)
        }
        .foregroundStyle(Theme.text).background(Theme.bg)
        .navigationTitle("Conversation info").navigationBarTitleDisplayMode(.inline)
        .toolbarBackground(Theme.surface, for: .navigationBar)
        .toolbarBackground(.visible, for: .navigationBar)
        .tint(Theme.brand).preferredColorScheme(.dark)
        .fullScreenCover(item: $viewer) { ArtifactViewer(item: $0) }
        .sheet(item: $preview, onDismiss: clearPreview) { QuickLookPreview(url: $0.url) }
        .alert("Unable to open file", isPresented: Binding(
            get: { fileError != nil }, set: { if !$0 { fileError = nil } }
        )) {
            Button("OK", role: .cancel) { fileError = nil }
        } message: { Text(fileError ?? "Please try again.") }
    }

    private var header: some View {
        VStack(spacing: 16) {
            Text(String(workspaceName.prefix(1)).uppercased()).themeFont(30, .semibold)
                .foregroundStyle(Theme.brand).frame(width: 72, height: 72)
                .background(Theme.brand.opacity(0.2), in: RoundedRectangle(cornerRadius: 26))
                .accessibilityHidden(true)
            Text(title).themeFont(22, .semibold).multilineTextAlignment(.center)
                .accessibilityAddTraits(.isHeader)
            Text(conversation.ticket == nil ? "Workspace conversation" : workspaceName)
                .themeFont(15).foregroundStyle(Theme.muted)
        }
        .frame(maxWidth: .infinity)
    }

    /// One row of tabs: short labels, the count as a small badge (only when there is something). They share the width
    /// when they fit; with large text the same row scrolls sideways instead of wrapping a label onto two lines.
    private func segments(_ all: [InfoEntry], referenceCount: Int) -> some View {
        let tabs = InfoGroup.allCases.map { g in (g, g == .links ? referenceCount : entries(in: g, from: all).count) }
        return ViewThatFits(in: .horizontal) {
            HStack(spacing: 4) { ForEach(tabs, id: \.0) { tabButton($0.0, count: $0.1, fill: true) } }
            ScrollViewReader { reader in
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 4) { ForEach(tabs, id: \.0) { tabButton($0.0, count: $0.1, fill: false).id($0.0) } }
                }
                .onAppear { reader.scrollTo(selection, anchor: .center) }   // the selected tab is always in view
                .onChange(of: selection) { _, new in withAnimation { reader.scrollTo(new, anchor: .center) } }
            }
        }
        .padding(4).background(Theme.surface2, in: RoundedRectangle(cornerRadius: 14))
    }

    private func tabButton(_ group: InfoGroup, count: Int, fill: Bool) -> some View {
        Button { selection = group } label: {
            HStack(spacing: 5) {
                Text(group.title).themeFont(13, .semibold).lineLimit(1).fixedSize()
                if count > 0 {
                    Text("\(count)").themeFont(11, .semibold).lineLimit(1).fixedSize()
                        .padding(.horizontal, 5).padding(.vertical, 1)
                        .background(Theme.surface3, in: Capsule())
                        .accessibilityHidden(true)
                }
            }
            .foregroundStyle(selection == group ? Theme.brand : Theme.muted)
            .padding(.horizontal, 10).frame(maxWidth: fill ? .infinity : nil, minHeight: 44)
            .background(selection == group ? Theme.surface3 : Theme.surface2, in: RoundedRectangle(cornerRadius: 11))
        }
        .buttonStyle(.plain)
        .accessibilityLabel("\(group.title), \(count) items")
        .accessibilityAddTraits(selection == group ? .isSelected : [])
        .accessibilityIdentifier("info-tab-\(group.rawValue)")
    }

    @ViewBuilder private func content(_ selected: [InfoEntry]) -> some View {
        if selected.isEmpty {
            Text("Nothing shared yet.").themeFont(15).foregroundStyle(Theme.muted)
                .frame(maxWidth: .infinity).padding(.vertical, 32)
        } else if selection == .photos {
            LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 8), count: 3), spacing: 8) {
                ForEach(selected) { entry in
                    Button { viewer = entry.item } label: { InfoThumbnail(blobID: entry.item.blobId) }
                        .buttonStyle(.plain)
                        .accessibilityLabel("Open photo, \(entry.item.title)")
                        .accessibilityIdentifier("info-item-\(entry.id)")
                }
            }
        } else {
            LazyVStack(spacing: 12) {
                ForEach(selected) { entry in
                    Button { open(entry) } label: {
                        if selection == .artifacts { artifactCard(entry) }
                        else { row(entry) }
                    }
                    .buttonStyle(.plain)
                    .disabled(loadingFile)
                    .accessibilityLabel("Open \(entry.item.title), \(entry.kindLabel)")
                    .accessibilityIdentifier("info-item-\(entry.id)")
                }
            }
        }
    }

    @ViewBuilder private func referenceContent(_ rows: [RefRow], links: [InfoEntry]) -> some View {
        if rows.isEmpty && links.isEmpty {
            Text("Nothing shared yet.").themeFont(15).foregroundStyle(Theme.muted)
                .frame(maxWidth: .infinity).padding(.vertical, 32)
        } else {
            LazyVStack(spacing: 12) {
                ForEach(rows) { row in
                    referenceRow(row).accessibilityIdentifier("info-ref-\(row.id)")
                }
                ForEach(links) { entry in
                    Button { open(entry) } label: { row(entry) }
                        .buttonStyle(.plain)
                        .accessibilityIdentifier("info-item-\(entry.id)")
                }
            }
        }
    }

    @ViewBuilder private func referenceRow(_ row: RefRow) -> some View {
        switch row {
        case .link(_, let title, let host, let url):
            Button { openURL(url) } label: {
                referenceLabel(title, detail: host, symbol: "link")
            }.buttonStyle(.plain)
        case .ticket(let id, let label, let known):
            Button {
                if known, let target = refs.enumerated().first(where: { "ref\($0.offset)" == id })?.element.ticket {
                    model.path.append(ChatRoute.ticket(workspace: conversation.workspace, ticket: target))
                }
            } label: {
                referenceLabel(label, symbol: "arrow.turn.down.right", chevron: true)
            }.buttonStyle(.plain).disabled(!known).opacity(known ? 1 : 0.5)
        case .artifact(_, let name, let item):
            if let item {
                Button { viewer = item } label: {
                    artifactCard(item, title: item.title, kindLabel: item.kind == .pdf ? "PDF" : "Artifact")
                }.buttonStyle(.plain)
            } else {
                artifactCard(nil, title: name, kindLabel: "Artifact").opacity(0.5)
            }
        case .file(_, let text):
            Text(text).font(.system(size: 15, design: .monospaced))
                .frame(maxWidth: .infinity, minHeight: 44, alignment: .leading).padding(16)
                .background(Theme.surface2, in: RoundedRectangle(cornerRadius: 14))
        }
    }

    private func referenceLabel(_ title: String, detail: String? = nil, symbol: String, chevron: Bool = false) -> some View {
        HStack(spacing: 12) {
            Image(systemName: symbol).themeFont(22).foregroundStyle(Theme.brand).accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 4) {
                Text(title).themeFont(16, .medium)
                if let detail { Text(detail).themeFont(13).foregroundStyle(Theme.muted) }
            }.multilineTextAlignment(.leading)
            Spacer(minLength: 0)
            if chevron { ShellChevron() }
        }
        .frame(maxWidth: .infinity, minHeight: 44, alignment: .leading).padding(16)
        .background(Theme.surface2, in: RoundedRectangle(cornerRadius: 14))
    }

    private func row(_ entry: InfoEntry) -> some View {
        HStack(spacing: 12) {
            Image(systemName: selection == .links ? "link" : "doc")
                .themeFont(22).foregroundStyle(Theme.brand).accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 4) {
                Text(entry.item.title).themeFont(16, .medium)
                Text(selection == .links ? (entry.item.url?.host ?? "Link") : entry.fileDetail)
                    .themeFont(13).foregroundStyle(Theme.muted)
            }
            Spacer(minLength: 0)
        }
        .frame(maxWidth: .infinity, minHeight: 44, alignment: .leading).padding(16)
        .background(Theme.surface2, in: RoundedRectangle(cornerRadius: 14))
    }

    private func artifactCard(_ entry: InfoEntry) -> some View {
        artifactCard(entry.item, title: entry.item.title, kindLabel: entry.kindLabel)
    }

    private func artifactCard(_ item: ArtifactItem?, title: String, kindLabel: String) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Image(systemName: item?.kind == .pdf ? "doc.richtext" : "globe")
                .themeFont(40).foregroundStyle(Theme.brand)
                .frame(maxWidth: .infinity, minHeight: 120)
                .background(Theme.surface3).accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 6) {
                Text(title).themeFont(16, .semibold)
                Text(kindLabel).themeFont(13).foregroundStyle(Theme.muted)
                if item != nil {
                    Label("Open", systemImage: "arrow.up.right").themeFont(13, .semibold)
                        .foregroundStyle(Theme.brand).padding(.top, 4)
                }
            }
            .padding(14)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Theme.surface2, in: RoundedRectangle(cornerRadius: 14))
        .clipShape(RoundedRectangle(cornerRadius: 14))
    }

    private func open(_ entry: InfoEntry) {
        let item = entry.item
        switch item.kind {
        case .image, .html, .pdf: viewer = item
        case .link:
            guard let url = item.safeLinkURL else { return }
            openURL(url)
        case .file:
            if !ArtifactItem.previewName(item.name ?? item.title).previewable { viewer = item; return }   // share only, never previewed in the app
            guard !loadingFile else { return }
            loadingFile = true
            Task { @MainActor in
                defer { loadingFile = false }
                guard let blobID = item.blobId, let bytes = await model.blob(blobID) else {
                    fileError = "The file could not be downloaded. Please try again."
                    return
                }
                let folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
                do {
                    try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
                    let url = folder.appendingPathComponent(ArtifactItem.previewName(item.name ?? item.title).safe)
                    try bytes.write(to: url, options: .atomic)
                    guard ArtifactItem.canPreview(fileName: url.lastPathComponent) else { throw CocoaError(.fileWriteInvalidFileName) }
                    clearPreview()
                    previewFolder = folder
                    preview = InfoPreview(url: url)
                } catch {
                    try? FileManager.default.removeItem(at: folder)
                    fileError = "The file could not be prepared for preview. Please try again."
                }
            }
        }
    }

    private func clearPreview() {
        if let folder = previewFolder { try? FileManager.default.removeItem(at: folder) }
        previewFolder = nil
    }
}

enum InfoGroup: String, CaseIterable, Identifiable {
    case photos, files, links, artifacts
    var id: String { rawValue }
    var title: String { self == .links ? "References" : rawValue.capitalized }
}

struct InfoEntry: Identifiable {
    let item: ArtifactItem
    let group: InfoGroup
    let kind: String
    let size: Int?
    let at: String
    let isTicket: Bool
    var id: String { item.id }
    var kindLabel: String {
        if item.kind == .pdf { return "PDF" }
        if kind == "FILE", let name = item.name {
            let ext = (name as NSString).pathExtension
            if !ext.isEmpty { return ext.uppercased() }
        }
        return kind
    }
    var fileDetail: String {
        guard let size else { return kindLabel }
        return "\(kindLabel) - \(ByteCountFormatter.string(fromByteCount: Int64(size), countStyle: .file))"
    }
}

private struct InfoPreview: Identifiable {
    let url: URL
    var id: URL { url }
}

@MainActor
private struct InfoThumbnail: View {
    let blobID: String?
    @Environment(AppModel.self) private var model
    @State private var image: UIImage?

    var body: some View {
        Color.clear.aspectRatio(1, contentMode: .fit)
            .overlay {
                GeometryReader { geometry in
                    ZStack {
                        Theme.surface2
                        if let image {
                            Image(uiImage: image).resizable().scaledToFill()
                                .frame(width: geometry.size.width, height: geometry.size.height)
                        }
                    }
                }
            }
            .clipShape(RoundedRectangle(cornerRadius: 8))
            .task(id: blobID) {
                image = nil
                guard let blobID, let data = await model.blob(blobID), !Task.isCancelled else { return }
                image = ThumbnailCache.image(id: blobID, data: data)
            }
    }
}

/// Which attachments of a conversation go into Photos / Files / References / Artifacts, newest first and without duplicates.
enum InfoGrouping {
    static func entries(messages: [ConvItem], ticketAttachments: [TicketSnapshot.Attachment], ticketAt: String,
                        conversation: ConversationID) -> [InfoEntry] {
        var result: [InfoEntry] = []
        for message in messages {
            for attachment in message.attachments where attachment.kind != .voice {
                result.append(InfoEntry(item: ArtifactItem(attachment, in: conversation),
                                        group: attachment.kind == .image ? .photos : .files,
                                        kind: attachment.kind == .image ? "IMAGE" : "FILE",
                                        size: attachment.size, at: message.at, isTicket: false))
            }
        }
        for attachment in ticketAttachments {
            let group: InfoGroup
            switch attachment.kind {
            case "image": group = .photos
            case "file": group = .files
            case "link": group = .links
            case "html", "pr", "commit": group = .artifacts
            default: continue
            }
            var item = ArtifactItem(attachment, in: conversation)
            if group == .links, attachment.label == nil { item.title = item.url?.host ?? "Link" }
            result.append(InfoEntry(item: item, group: group, kind: attachment.kind.uppercased(),
                                    size: attachment.size, at: attachment.at ?? ticketAt, isTicket: true))
        }
        return result.sorted {
            if $0.at != $1.at { return $0.at > $1.at }
            if $0.isTicket != $1.isTicket { return $0.isTicket }
            return $0.id < $1.id
        }
    }

    static func entries(in group: InfoGroup, from all: [InfoEntry]) -> [InfoEntry] {
        var seen = Set<String>()
        return all.filter { entry in
            let belongs = entry.group == group || (group == .artifacts && entry.isTicket && entry.item.kind == .pdf)
            guard belongs else { return false }
            let keys = [entry.item.blobId.map { "blob:\($0)" },
                        entry.item.artifactId.map { "artifact:\($0)" },
                        entry.item.url.map { "url:\($0.absoluteString)" }, "id:\(entry.id)"].compactMap { $0 }
            let duplicate = keys.contains { seen.contains($0) }
            seen.formUnion(keys)
            return !duplicate
        }
    }
}

/// Small decoded thumbnails (<= 300 px) kept in memory for the info grid.
@MainActor
enum ThumbnailCache {
    private static let cache = NSCache<NSString, UIImage>()
    static func image(id: String, data: Data) -> UIImage? {
        if let hit = cache.object(forKey: id as NSString) { return hit }
        guard let src = CGImageSourceCreateWithData(data as CFData, nil) else { return nil }
        let opts: [CFString: Any] = [kCGImageSourceCreateThumbnailFromImageAlways: true, kCGImageSourceCreateThumbnailWithTransform: true,
                                     kCGImageSourceThumbnailMaxPixelSize: 300]
        guard let cg = CGImageSourceCreateThumbnailAtIndex(src, 0, opts as CFDictionary) else { return nil }
        let image = UIImage(cgImage: cg)
        cache.setObject(image, forKey: id as NSString)
        return image
    }
}
