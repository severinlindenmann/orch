import SwiftUI

struct HomeView: View {
    @Environment(AppModel.self) private var model
    @State private var expandedTags: Set<String> = []

    private var greeting: String {
        switch Calendar.current.component(.hour, from: Date()) {
        case 5..<12: "Good morning"
        case 12..<18: "Good afternoon"
        default: "Good evening"
        }
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                Brand().padding(.bottom, 28)
                Eyebrow(text: greeting.uppercased(), color: Theme.brand).padding(.bottom, 12)
                ScreenHeading(title: "Your workspaces.", subtitle: model.openQuestionCount > 0 ? "\(model.openQuestionCount == 1 ? "One thing needs" : "A few things need") your answer." : "All clear. Nothing needs you right now.")
                if model.openQuestionCount > 0 {
                    Button { model.questionFilter = nil; model.tab = .questions } label: {
                        HStack(spacing: 12) {
                            Text("?").font(Theme.font(18)).frame(width: 30, height: 30)
                                .background(Theme.brand.opacity(0.1), in: Circle()).foregroundStyle(Theme.brand)
                            VStack(alignment: .leading, spacing: 3) {
                                Text(model.openQuestionCount == 1 ? "1 question for you" : "\(model.openQuestionCount) questions for you").font(Theme.font(13, .semibold))
                                Text("A quick answer keeps things moving.").font(Theme.font(10)).foregroundStyle(Theme.muted)
                            }
                            Spacer(minLength: 0)
                            Image(systemName: "chevron.right").font(Theme.font(13, .semibold)).foregroundStyle(Theme.brand)
                        }.padding(.horizontal, 12).padding(.vertical, 16)
                            .background(Theme.brand.opacity(0.04), in: RoundedRectangle(cornerRadius: 10))
                            .overlay(RoundedRectangle(cornerRadius: 10).stroke(Theme.brand.opacity(0.27)))
                    }.buttonStyle(.plain).padding(.top, 26)
                }
                HStack { Eyebrow(text: "WORKSPACES"); Spacer(); Eyebrow(text: "\(model.workspaces.count)") }
                    .padding(.top, 30).padding(.bottom, 12)
                if !model.hasLoaded && model.workspaces.isEmpty && model.message == nil {
                    ForEach(0..<2, id: \.self) { _ in
                        workspaceRow(Workspace(id: "x", name: "Workspace name", description: "What this workspace does", tags: [], online: true, lastSeen: nil, openQuestions: 0))
                    }.skeleton(true).accessibilityHidden(true)
                }
                ForEach(model.workspaces) { workspace in workspaceRow(workspace) }
                if model.workspaces.isEmpty && model.hasLoaded {
                    VStack(alignment: .leading, spacing: 6) {
                        Text("No workspaces yet").font(Theme.font(15, .semibold))
                        Text("Ask the person who invited you to add a workspace. It will show up here.")
                            .font(Theme.font(13)).foregroundStyle(Theme.muted)
                    }.orchCard()
                }
                ModelMessage().padding(.top, 12)
            }.padding(.horizontal, 23).padding(.top, 6).padding(.bottom, 20)
        }.refreshable { await model.refresh() }
            .animation(.easeOut(duration: 0.25), value: model.workspaces)
    }

    private func workspaceRow(_ workspace: Workspace) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 0) {
                Button {
                    model.questionFilter = workspace.id; model.tab = .questions
                } label: {
                    HStack(spacing: 10) {
                        Text(String(workspace.displayName.prefix(1))).font(Theme.font(14))
                            .frame(width: 35, height: 35).foregroundStyle(Theme.brand)
                            .background(Theme.brand.opacity(0.1), in: RoundedRectangle(cornerRadius: 9))
                        VStack(alignment: .leading, spacing: 3) {
                            Text(workspace.displayName).font(Theme.font(14, .medium))
                            if let description = workspace.description {
                                Text(description).font(Theme.font(12)).foregroundStyle(Theme.muted)
                            }
                            HStack(spacing: 4) {
                                Circle().fill(workspace.online ? Theme.brand : Theme.muted).frame(width: 5, height: 5)
                                Text(lastSeenText(workspace.lastSeen, online: workspace.online)).foregroundStyle(Theme.muted)
                            }.font(Theme.font(12))
                        }.frame(maxWidth: .infinity, alignment: .leading)
                        if workspace.openQuestions > 0 {
                            Text("\(workspace.openQuestions)").font(Theme.font(11)).foregroundStyle(Theme.brand)
                                .padding(.horizontal, 7).padding(.vertical, 2)
                                .background(Theme.brand.opacity(0.1), in: RoundedRectangle(cornerRadius: 5))
                        }
                    }.frame(minHeight: 44).contentShape(Rectangle())
                }.buttonStyle(.plain)
                Button {
                    if expandedTags.contains(workspace.id) { expandedTags.remove(workspace.id) }
                    else { expandedTags.insert(workspace.id) }
                } label: {
                    Image(systemName: expandedTags.contains(workspace.id) ? "chevron.up" : "chevron.down")
                        .font(Theme.font(12)).frame(width: 44, height: 44)
                }.foregroundStyle(Theme.muted).accessibilityLabel("Tags for \(workspace.displayName)")
                    .accessibilityValue(expandedTags.contains(workspace.id) ? "Expanded" : "Collapsed")
                    .accessibilityIdentifier("tags-\(workspace.id)")
            }
            if expandedTags.contains(workspace.id) {
                Text(workspace.tags.joined(separator: " · ")).font(Theme.font(11)).foregroundStyle(Theme.muted)
                    .padding(.leading, 45)
            }
        }.padding(.vertical, 17)
            .overlay(alignment: .bottom) { Rectangle().fill(Theme.border).frame(height: 1) }
    }
}
