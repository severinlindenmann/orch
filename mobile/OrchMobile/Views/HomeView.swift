import SwiftUI

struct HomeView: View {
    @Environment(AppModel.self) private var model
    @State private var expandedTags: Set<String> = []

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                HStack {
                    Brand()
                    Spacer()
                    Button { model.tab = .settings } label: {
                        Image(systemName: "person.fill").font(.system(size: 11))
                            .frame(width: 32, height: 32).background(Theme.surface2, in: Circle())
                            .overlay(Circle().stroke(Theme.border)).frame(width: 44, height: 44)
                    }.foregroundStyle(Theme.muted).accessibilityLabel("Open settings")
                }.padding(.bottom, 28)
                Eyebrow(text: "GOOD MORNING", color: Theme.brand).padding(.bottom, 12)
                ScreenHeading(title: "Your workspaces.", subtitle: model.openQuestionCount > 0 ? "Just a few things need your input." : "All clear. Nothing needs you right now.")
                if model.openQuestionCount > 0 {
                    Button { model.questionFilter = nil; model.tab = .questions } label: {
                        HStack(spacing: 12) {
                            Text("?").font(.system(size: 18)).frame(width: 30, height: 30)
                                .background(Theme.brand.opacity(0.1), in: Circle()).foregroundStyle(Theme.brand)
                            VStack(alignment: .leading, spacing: 3) {
                                Text("\(model.openQuestionCount) questions for you").font(.system(size: 13, weight: .semibold))
                                Text("A quick answer keeps things moving.").font(.system(size: 10)).foregroundStyle(Theme.muted)
                            }
                            Spacer(minLength: 0)
                            Text("↗").foregroundStyle(Theme.brand)
                        }.padding(.horizontal, 12).padding(.vertical, 16)
                            .background(Theme.brand.opacity(0.04), in: RoundedRectangle(cornerRadius: 10))
                            .overlay(RoundedRectangle(cornerRadius: 10).stroke(Theme.brand.opacity(0.27)))
                    }.buttonStyle(.plain).padding(.top, 26)
                }
                HStack { Eyebrow(text: "CONNECTED WORKSPACES"); Spacer(); Eyebrow(text: "\(model.workspaces.count)") }
                    .padding(.top, 30).padding(.bottom, 12)
                ForEach(model.workspaces) { workspace in workspaceRow(workspace) }
                Button { model.tab = .send } label: {
                    HStack(spacing: 12) {
                        Text("＋").font(.system(size: 20)).foregroundStyle(Theme.brand)
                        VStack(alignment: .leading, spacing: 3) {
                            Text("Something on your mind?").font(.system(size: 12, weight: .semibold))
                            Text("Send a note to a workspace.").font(.system(size: 11)).foregroundStyle(Theme.muted)
                        }
                        Spacer(minLength: 0)
                        Text("↗").foregroundStyle(Theme.brand)
                    }.padding(.vertical, 18).padding(.horizontal, 14)
                        .overlay(RoundedRectangle(cornerRadius: 10).stroke(Theme.border, style: StrokeStyle(lineWidth: 1, dash: [4, 3])))
                }.buttonStyle(.plain).padding(.top, 30)
                HStack(spacing: 4) {
                    Text("●").foregroundStyle(Theme.brand)
                    Text("Connected to \(model.relayHost)").foregroundStyle(Theme.muted)
                }.font(.system(size: 10)).frame(maxWidth: .infinity).padding(.top, 25)
                ModelMessage().padding(.top, 12)
            }.padding(.horizontal, 23).padding(.top, 6).padding(.bottom, 20)
        }.refreshable { await model.refresh() }
    }

    private func workspaceRow(_ workspace: Workspace) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 0) {
                Button {
                    model.questionFilter = workspace.id; model.tab = .questions
                } label: {
                    HStack(spacing: 10) {
                        Text(String(workspace.name.prefix(1))).font(.system(size: 14))
                            .frame(width: 35, height: 35).foregroundStyle(Theme.brand)
                            .background(Theme.brand.opacity(0.1), in: RoundedRectangle(cornerRadius: 9))
                        VStack(alignment: .leading, spacing: 3) {
                            Text(workspace.name).font(.system(size: 13, weight: .medium))
                            if let description = workspace.description {
                                Text(description).font(.system(size: 10)).foregroundStyle(Theme.muted)
                            }
                            HStack(spacing: 4) {
                                Circle().fill(workspace.online ? Theme.brand : Theme.muted).frame(width: 5, height: 5)
                                Text(lastSeenText(workspace.lastSeen, online: workspace.online)).foregroundStyle(Theme.muted)
                            }.font(.system(size: 10))
                        }.frame(maxWidth: .infinity, alignment: .leading)
                        if workspace.openQuestions > 0 {
                            Text("\(workspace.openQuestions)").font(.system(size: 11)).foregroundStyle(Theme.warn)
                                .padding(.horizontal, 7).padding(.vertical, 2)
                                .background(Theme.warn.opacity(0.1), in: RoundedRectangle(cornerRadius: 5))
                        }
                    }.frame(minHeight: 44).contentShape(Rectangle())
                }.buttonStyle(.plain)
                Button {
                    if expandedTags.contains(workspace.id) { expandedTags.remove(workspace.id) }
                    else { expandedTags.insert(workspace.id) }
                } label: {
                    Image(systemName: expandedTags.contains(workspace.id) ? "chevron.up" : "chevron.down")
                        .font(.system(size: 12)).frame(width: 44, height: 44)
                }.foregroundStyle(Theme.muted).accessibilityLabel("Tags for \(workspace.name)")
                    .accessibilityValue(expandedTags.contains(workspace.id) ? "Expanded" : "Collapsed")
                    .accessibilityIdentifier("tags-\(workspace.id)")
            }
            if expandedTags.contains(workspace.id) {
                Text(workspace.tags.joined(separator: " · ")).font(.system(size: 11)).foregroundStyle(Theme.muted)
                    .padding(.leading, 45)
            }
        }.padding(.vertical, 17)
            .overlay(alignment: .bottom) { Rectangle().fill(Theme.border).frame(height: 1) }
    }
}
