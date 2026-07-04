# Not for ai agents, claude, antigravity, opencode, or anyother, 
# only for user ideas and findings

1. generate once is not working if session is not started, 
    question is do we actually need it? or can be skipped, 
    question is should we add image generation button in chat section or keep only the ImageLab
    --- claude dont support image generation, so its not that it is a basic need

2. we can also use kaggle notebook to use kaggle given models via apis, 
    --- either by hosting and running model on kaggle
    --- or by api, but using notebook as intermediate

3. the model selection button is removed from search bar tab

4.  Two Branch Setup Private+Public
``` 
To manage a two-repository setup efficiently, you use Git Remotes. Your local project folder will link to both repositories, allowing you to develop privately and push to the public repo only when ready.Here is the step-by-step management workflow.🏗️ Step 1: Link Both Repositories LocallyOpen your terminal inside your existing local project folder and link both URLs.Rename your existing remote to private (if it is currently named origin):bashgit remote rename origin private
Use code with caution.Add your new public repository as a second remote named public:bashgit remote add public https://github.com
Use code with caution.Verify your remotes are set up correctly:bashgit remote -v
Use code with caution.(You should see four lines: two for private and two for public)🔄 Step 2: The Daily Development WorkflowYou will do 99% of your work inside the private repository.Create feature branches and push them safely to your private repo:bashgit checkout -b feature-xyz
# ... do your code work ...
git push private feature-xyz
Use code with caution.Merge your work into your private main branch when it is ready for release:bashgit checkout main
git merge feature-xyz
git push private main
Use code with caution.🚀 Step 3: Publishing to the PublicWhen you are ready to share your code changes with the world, run just one command to sync the public repository:bashgit push public main
Use code with caution.Because you only ever run git push public main, no other branches will ever upload to the public GitHub repository.⚠️ Crucial Rules for Managing This SetupNever use git push --all: This command pushes every single branch to your default remote. Avoid it entirely to prevent accidental leaks.Keep .gitignore identical: Ensure both repositories use the exact same .gitignore file so private API keys or configuration files do not accidentally get pushed to the public repo.Squash commits (Optional but Recommended): If your private commit messages contain sensitive or messy notes, use git merge --squash when merging into main. This combines all your feature history into one clean commit before you push it to the public.To make things even easier, I can give you a GitHub Actions automation script that automatically pushes to the public repo every time you update your private main branch. Would you like to set that up?
```
